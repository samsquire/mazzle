#!/usr/bin/env python3
from threading import Thread, Lock
from functools import reduce
import itertools
import time
import collections
import getpass
from functools import partial
from flask import Flask, render_template, Response
from flask_socketio import SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

import os
cwd = os.getcwd()
project_directory = os.getcwd()

import psutil
from argparse import ArgumentParser
from networkx.drawing.nx_pydot import read_dot, write_dot
from networkx.readwrite import json_graph
from pssh.clients import ParallelSSHClient, SSHClient
from pssh.utils import load_private_key
from gevent import joinall
import networkx as nx
import sys, json

import sys
dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(dir_path)

from sys import stdout
from pprint import pprint
from subprocess import Popen, PIPE, run, call
from component_scheduler import scheduler
from networkx.algorithms.dag import ancestors

parser = ArgumentParser(description="devops-pipeline")
parser.add_argument("--file", default="architecture.dot")
parser.add_argument("--environment")

lock = Lock()
args = parser.parse_args()

global_commands = ["package", "validate", "plan", "run", "test", "publish"]

dot_graph = read_dot(args.file)
environment_graph = read_dot("environments.dot")
G = dot_graph

for node in list(dot_graph.nodes()):
    steps = global_commands
    for step in steps:
        step_name = "{}/{}".format(node, step)
        dot_graph.add_node(step_name)
    for previous, after in zip(steps, steps[1:]):
        G.add_edge("{}/{}".format(node, previous), "{}/{}".format(node, after))
    for parent in G.predecessors(node):
        G.add_edge(parent, "{}/{}".format(node, "package"))
    for children in G.successors(node):
        G.add_edge("{}/{}".format(node, "publish"), children)
    dot_graph.remove_node(node)

tree = nx.topological_sort(dot_graph)
ordered_environments = list(nx.topological_sort(environment_graph))

write_dot(dot_graph, "architecture.expanded.dot")

ordering = list(tree)

loaded_components = []
for count, node in enumerate(ordering):
    component_ancestors = list(ancestors(G, node))
    predecessors = list(G.predecessors(node))
    successors = list(G.successors(node))
    loaded_components.append({
        "name": node,
        "ancestors": predecessors,
        "successors": successors
    })

print("Scheduling components into run groups...")
streams, orderings = scheduler.parallelise_components(loaded_components)

loaded_json_file = open("builds/loaded.json", "w")
loaded_json_file.write(json.dumps(loaded_components, indent=4))

pprint(streams)
stream_file = open("builds/run_groups", "w")
pprint(streams, stream=stream_file)
stream_file.flush()
stream_file.close()

state = {
"environments": [
],
"components": [],
"pipeline": [],
"running": [],
"latest": [{
"name": "terraform/vpc",
"commands": [
    {"name": 'validate', "buildIdentifier": '21', "progress": 100},
    {"name": 'test', "buildIdentifier": '21', "progress": 100},
    {"name": 'package', "buildIdentifier": '21', "progress": 60},
    {"name": 'plan', "buildIdentifier": '21', "progress": 0},
    {"name": 'run', "buildIdentifier": '21', "progress": 0},
    {"name": 'deploy', "buildIdentifier": '21', "progress": 0},
    {"name": 'release', "buildIdentifier": '21', "progress": 0},
    {"name": 'smoke', "buildIdentifier": '21', "progress": 0}
    ]
}],
"filtering": ""
}

def get_last_run_path(environment, provider, component, command):
    return os.path.join(project_directory, "builds/last_runs/{}.{}.{}.{}.last_run".format(environment, provider, component, command))


def parse_reference(reference):
  full_provider, component_name, command = reference.split("/")
  provider = full_provider.replace("@", "")
  component = component_name.replace("*","")
  return (provider, component, command, "*" in component_name, "@" in full_provider)

def find_last_successful_build(builds):
    for build in reversed(builds):

      if build["success"] == True:
          return build
    return None

def get_exit_code_path(environment, provider, component, command):
    return os.path.join(project_directory, "builds/exits/{}.{}.{}.{}.exitcode".format(environment, provider, component, command))

def construct_environment(environment, provider, component, command, previous_outputs):
    env = {
        "OUTPUT_PATH": os.path.join(project_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command)),
        "EXIT_CODE_PATH": get_exit_code_path(environment, provider, component, command)
    }
    env.update(previous_outputs)
    env["ENVIRONMENT"] = str(environment)
    return env

def get_builds_filename(environment, provider, component, command):
    return os.path.join(project_directory, "builds/history/{}.{}.{}.{}.json".format(environment, provider, component, command))


def ensure_file(build_file):
  if (not os.path.isfile(build_file)) or (os.path.isfile(build_file) and os.stat(build_file).st_size == 0):
      builds_file = open(build_file, 'w')
      builds_file.write(json.dumps({
          "builds": []
      }, indent=4))
      builds_file.flush()
      builds_file.close()




def get_builds(environment, provider, component, command):
    lock.acquire()
    builds_file = get_builds_filename(environment, provider, component, command)
    ensure_file(builds_file)
    opened = open(builds_file)

    build_data = json.loads(opened.read())
    opened.close()
    builds = build_data["builds"]
    if len(builds) == 0:
        last_build_status = False
        next_build = 1
    else:
        last_build_status = builds[-1]["success"]
        next_build = builds[-1]["build_number"] + 1
    lock.release()
    return (builds, last_build_status, next_build)


def retrieve_outputs(environment, node):

    provider, component, command, manual, local = parse_reference(node)
    parents = list(ancestors(G, node))
    print("retrieving outputs for {}".format(node))
    env = {}
    for parent in parents:

      parent_provider, parent_component, parent_command, manual, parent_local = parse_reference(parent)
      parent_builds, last_build_status, next_build = get_builds(environment, parent_provider, parent_component, parent_command)

      last_successful_build = find_last_successful_build(parent_builds)

      if last_successful_build == None:
          # print("No successful build for {}".format(parwsent))
          continue

      pretty_build_number = "{:0>4d}".format(last_successful_build["build_number"])
      output_filename = "outputs/{}.{}.{}.{}.outputs.json".format(environment, parent_provider, parent_component, parent_command)
      if not os.path.isfile(output_filename):
          output_bucket = "vvv-{}-outputs".format(environment)
          s3_filename = "{}/{}/{}/{}.json".format(environment, parent_provider, parent_component, parent_command, pretty_build_number)
          s3_path = "s3://vvv-{}-outputs/{}/{}/{}/{}.json".format(environment, parent_provider, parent_component, parent_command, pretty_build_number)
          # check = run(["aws", "s3api", "head-object", "--bucket", output_bucket, "--key", s3_filename], stderr=open("s3log", "w"))

          #if check.returncode == 0:
            #  pass # run(["aws", "s3", "cp", s3_path, output_filename])
      outputs_path = os.path.abspath(os.path.join(project_directory, "builds", output_filename))

      if os.path.isfile(outputs_path):

          if os.stat(outputs_path).st_size != 0:
              loaded_outputs = json.loads(open(outputs_path).read())
              if 'secrets' in loaded_outputs:
                decoder = Popen(["base64", "-d", "--wrap=0"], stdin=PIPE, stdout=PIPE, stderr=sys.stderr)
                decrypter = Popen(["gpg", "--decrypt"], stdin=decoder.stdout, stdout=PIPE, stderr=sys.stderr)
                decoder.stdin.write(loaded_outputs['secrets'].encode('utf-8'))
                decoder.stdin.close()
                decrypted_result, err = decrypter.communicate()
                loaded_outputs['secrets'] = json.loads(decrypted_result.decode('utf-8'))


              env.update(loaded_outputs)

    unfiltered = dict(env)
    for key, value in env.items():
        if isinstance(value, list):
            cleaned = list(filter(lambda x:x != "", env[key]))
            unfiltered[key] = cleaned
            env[key] = " ".join(cleaned)
    return env, unfiltered

states = {}
class Worker(Thread):
    def __init__(self, threads, item):
        super(Worker, self).__init__()
        self.threads = threads
        self.item = item
        provider, component, command, manual, local = parse_reference(self.item["name"])
        self.provider = provider
        self.component = component
        self.command = command
        self.environment = args.environment
        self.error = False


    def run(self):
        for parent in self.item["ancestors"]:
            states[self.item["name"]] = "waiting"
            threads[parent].join()
            if threads[parent].error == True:
                states[self.item["name"]] = "aborted"
                return
        states[self.item["name"]] = "running"

        component_paths_script = os.path.join(self.provider, "component-paths")
        if os.path.isfile(component_paths_script):

           component_paths_output = run(["component-paths", self.environment, self.component],
               cwd=os.path.join(project_directory, self.provider), stdout=PIPE).stdout.decode('utf-8').strip()
           component_paths = component_paths_output.split("\n")

           last_run_path = get_last_run_path(self.environment, self.provider, self.component, self.command)

           if os.path.isfile(last_run_path):
               find_command = ["find"] + component_paths + ["(", "-path", "*.state", "-o", "-path",
               "*.terraform", ")", "-prune", "-o", "-newer", os.path.abspath(last_run_path), "-print"]
               # print(" ".join(find_command))
               changed_files = run(find_command,
                   cwd=os.path.join(project_directory, self.provider),
                   stdout=PIPE).stdout.decode('utf-8').split("\n")
               changed_files.pop()
               print(changed_files)
               if global_commands.index(self.command) != 0 and len(changed_files) == 0:
                   print("Component {}/{} is up-to-date".format(self.component, self.command))
                   states[self.item["name"]] = "up-to-date"
                   return

        log_filename = "logs/{}-{}-{}-{}.log".format(self.environment, self.provider, self.component, self.command)
        log_file = open(os.path.join(project_directory, log_filename), 'w')
        outputs, raw_outputs = retrieve_outputs(args.environment, self.item["name"])
        env = construct_environment(self.environment, self.provider, self.component, self.command, outputs)
        if os.path.isfile(os.path.join(self.provider, self.command)):

            runner = Popen([self.command,
               args.environment,
               self.component], cwd=self.provider, stdin=sys.stdin, stdout=log_file, stderr=log_file,
               env=env)
            runner.communicate(input=None, timeout=None)
            runner.wait(timeout=None)
            exit_code = int(open(env["EXIT_CODE_PATH"]).read())
            if exit_code != 0:
                states[self.item["name"]] = "error"
                self.error = True
                print("ERROR")
            else:
                open(os.path.join(get_last_run_path(self.environment, self.provider, self.component, self.command)), 'w').write(':)')

        states[self.item["name"]] = "finished"

class ThreadMonitor(Thread):
    def __init__(self, threads):
        super(ThreadMonitor, self).__init__()
        self.threads = threads
        self.running = True
    def run(self):

        while self.running:
            totals = {"running": 0, "waiting": 0, "finished": 0, "error": 0, "aborted": 0, "up-to-date": 0}
            running = []
            for name, thread in self.threads.items():
                state = states.get(name, "")
                totals[state] = totals[state] + 1
                if state == "running":
                    running.append(name)

            time.sleep(0.5)
            sys.stdout.write("\r\033[K{}                                "
                .format(" ".join(running)))
            sys.stdout.write("\n\r\033[K{} running {} waiting {} finished {} up-to-date {} error  {} aborted        "
                .format(totals["running"], totals["waiting"], totals["finished"], totals["up-to-date"], totals["error"], totals["aborted"]))
            sys.stdout.write("\033[F")

            if len(threads.items()) == totals["finished"]:
                self.running = False




print("Scheduling finished... Loading...")
threads = {}
for item in streams:
    threads[item["name"]] = Worker(threads, item)
for name, thread in threads.items():
    thread.start()

ThreadMonitor(threads).start()
