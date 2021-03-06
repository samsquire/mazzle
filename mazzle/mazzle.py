#!/usr/bin/env python3
from threading import Thread, Lock
from functools import reduce
import itertools
import collections
import getpass
from functools import partial
from flask import Flask, render_template, Response
from flask_socketio import SocketIO
from flask_cors import CORS

import os


import psutil
from argparse import ArgumentParser
from networkx.drawing.nx_pydot import read_dot, write_dot
from networkx.readwrite import json_graph
from pssh.clients import ParallelSSHClient, SSHClient
from pssh.utils import load_private_key
from gevent import joinall
import networkx as nx
import sys, json
import re
from shutil import copy

import sys
dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(dir_path)

from sys import stdout
from pprint import pprint
from subprocess import Popen, PIPE, run, call
import time

lock = Lock()
run_groups = []
job_monitors = {}

stream_workers = []
doer_cache = {}
state = {
"notifications": [],
"environments": [
],
"components": [],
"pipeline": [],
"running": [],
"latest": [
# {
# "name": "terraform/vpc",
# "commands": [
#     {"name": 'validate', "buildIdentifier": '21', "progress": 100},
#     {"name": 'test', "buildIdentifier": '21', "progress": 100},
#     {"name": 'package', "buildIdentifier": '21', "progress": 60},
#     {"name": 'plan', "buildIdentifier": '21', "progress": 0},
#     {"name": 'run', "buildIdentifier": '21', "progress": 0},
#     {"name": 'deploy', "buildIdentifier": '21', "progress": 0},
#     {"name": 'release', "buildIdentifier": '21', "progress": 0},
#     {"name": 'smoke', "buildIdentifier": '21', "progress": 0}
#     ]
#
# }
],
"filtering": "",
"parallelism": []
}
last_q = {
    "q": None
}
searchResults = {
    "environments": [],
    "components": [],
}

def remove_from_running(reference, environment):
  provider_name, component_name, command_name, manual, local_build = parse_reference(reference)
  for item in state["running"]:
      if item["environment"] == environment and item["reference"] == reference:
        state["running"].remove(item)

        for latest in state["latest"]:
            if latest["environment"] == environment and latest["name"] == "{}/{}".format(provider_name, component_name):
                for command in latest["commands"]:
                    if command["name"] == command_name:
                        command["status"] = "ready"
                        command["progress"] = 100

def mark_dependency_as_running(reference, environment):
    provider_name, component_name, command_name, manual, local_build = parse_reference(reference)

    for item in state["latest"]:
        if item["environment"] == environment and item["name"] == "{}/{}".format(provider_name, component_name):
            for command in item["commands"]:
                if command["name"] == command_name:
                    command["status"] = "running"

def parse_reference(reference):
  full_provider, component_name, command = reference.split("/")
  provider = full_provider.replace("@", "")
  component = component_name.replace("*","")
  return (provider, component, command, "*" in component_name, "@" in full_provider)

def get_last_run_path(environment, provider, component, command):
    return os.path.join(project_directory, "builds/last_runs/{}.{}.{}.{}.last_run".format(environment, provider, component, command))

def get_exit_code_path(work_directory, environment, provider, component, command, build_number):
    return os.path.join(work_directory, "builds/exits/{}.{}.{}.{}.{}.exitcode".format(environment, provider, component, command, build_number))

def get_pretty_build_number(build_number):
    return "{:0>4d}".format(build_number)


def render_pipeline(run_groups):
  group_count = 1
  for index, group in enumerate(run_groups):
      print("{}/{} Group".format(index + 1, len(run_groups)))
      for item in group:
          print("{}".format(item))
      print("")
      step_outputs, _ = retrieve_outputs(environment, item)
      print(step_outputs)

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

def write_builds_file(builds_filename, builds_data):
    f = open(builds_filename, 'w+')
    f.write(json.dumps(builds_data, sort_keys=True, indent=4))
    f.flush()
    f.close()

def get_outputs_filename(environment, provider, component, command):
    return os.path.abspath(os.path.join(project_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command)))

class Component():
    def __init__(self, reference, environment, provider, component, command, args):
        self.environment = environment
        self.provider = provider
        self.component = component
        self.command = command
        self.reference = reference
        self.args = args

    def handle_success(self, build):
        environment = self.environment
        provider = self.provider
        component = self.component
        command = self.command
        dependency = self.reference
        build_number = build["build_number"]
        outputs_filename = get_outputs_filename(environment, provider, component, command)
        print(outputs_filename)
        decoded = None
        try:
            outputs_file = open(outputs_filename)
            decoded = json.loads(outputs_file.read())
            outputs_file.close()
        except:
            return
        pretty_build_number = "{:0>4d}".format(build_number)
        if 'secrets' in decoded:
          secrets = decoded.pop('secrets')
          recipient_list = list(map(lambda key: ["--recipient", key], self.args.keys))
          encrypt_command = ["gpg"] + list(itertools.chain(*recipient_list)) + ["--encrypt"]
          print(encrypt_command)
          encrypter = Popen(encrypt_command, stdin=PIPE, stdout=PIPE, stderr=sys.stderr)
          encoder = Popen(["base64", "--wrap=0"], stdin=encrypter.stdout, stdout=PIPE, stderr=sys.stderr)
          decrypted = json.dumps(secrets).encode('utf-8')

          encrypter.stdin.write(decrypted)
          encrypter.stdin.close()
          encrypted_secrets, err = encoder.communicate()
          decoded["secrets"] = encrypted_secrets.decode('utf-8')


        # Write our outputs to the output bucket
        # builds/outputs/{}.{}.{}.{}.outputs.json
        with open(outputs_filename, 'w') as output_file:
          output_file.write(json.dumps(decoded))
        # run(["aws", "s3", "cp", output_filename, "s3://vvv-{}-outputs/{}/{}/{}/{}.json"
        #    .format(environment, provider, component, command, pretty_build_number)])

        # env.update(json.loads(outputs))
        # pprint(env)

        print("{} {} Build passed".format(dependency, pretty_build_number))
        # run(["git", "tag", "-d", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)
        # run(["git", "tag", "pipeline/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)

        last_run_path = get_last_run_path(environment, provider, component, command)
        open(os.path.join(last_run_path), 'w').write(':)')

    def calculate_state(self):
        builds, last_build_status, next_build = get_builds(self.environment, self.provider, self.component, self.command)
        last_running_build = None
        for build in builds:
            build_number = build["build_number"]
            exit_code_path = os.path.abspath(get_exit_code_path(project_directory, self.environment, self.provider, self.component, self.command, build_number))

            if "pid" in build and not os.path.isfile(exit_code_path) and build.get('status') == "running":
                if not psutil.pid_exists(build["pid"]):
                    build["status"] = "failure"

            if os.path.isfile(exit_code_path) and build.get('status') == "running":
                print("Build is running and has exit code set")
                last_running_build = build
                build["status"] = "finished"
                exit_code_data = open(exit_code_path).read()
                exit_code = int(exit_code_data)
                if exit_code == 0:
                    print("Exit code is good")
                    build["success"] = True
                    outputs_filename = get_outputs_filename(self.environment, self.provider, self.component, self.command)
                    if os.path.isfile(outputs_filename):
                        print("Have outputs file")
                        self.handle_success(build)
                    else:
                        print("No outputs file for running build")
                        build["success"] = False
                        build["status"] = "unknown"
                else:
                    print("{} Build failure".format(build["reference"]))
                    build["success"] = False
            if "pid" not in build and build["status"] == "running":
                build["status"] = "unknown"


        remove_from_running(self.reference, self.environment)
        lock.acquire()
        builds_filename = get_builds_filename(self.environment, self.provider, self.component, self.command)
        write_builds_file(builds_filename, {"builds": builds})
        lock.release()
        return last_running_build



# "/home/sam/projects/backup-infra/.vagrant/machines/node1/virtualbox/private_key"
parser = ArgumentParser(description="mazzle")
parser.add_argument("--change-directory")
parser.add_argument("--file", default="architecture.dot")
parser.add_argument("--environments", default="environments.dot")
parser.add_argument("--discover-workers-from-output")
parser.add_argument("--workers", nargs="+", default=[] )
parser.add_argument("--workers-key", nargs="+", default=[])
parser.add_argument("--workers-user", default=None)
parser.add_argument("--keys", nargs="+", default=[] )
parser.add_argument("--gui", action="store_true" )
parser.add_argument("--force", action="store_true" )
parser.add_argument("--only", nargs='+', default=[])
parser.add_argument("--ignore", nargs='+', default=[])
parser.add_argument("--force-local", action="store_true", default=False)
parser.add_argument("--rebuild", nargs='+', default=[])
parser.add_argument("--manual", nargs='+', default=[])
parser.add_argument("--no-trigger", action="store_true", default=False)
parser.add_argument("environment")

args = parser.parse_args(os.environ["MAZZLE_ARGS"].split(" "))

if args.change_directory:
    os.chdir(args.change_directory)
cwd = os.getcwd()
project_directory = os.getcwd()

print(project_directory)

for path in ["builds/artifacts", "builds/environments", "builds/exits",
    "builds/history", "builds/last_runs", "builds/envs", "builds/work",
    "builds/outputs", "builds/published", "builds/logs"]:
    if not os.path.isdir(path):
        os.makedirs(path)

def matcher(item, pattern):
    if item.replace("@", "").startswith(pattern):
        return True
    if item == pattern:
        return True
    if pattern == "":
        return True
    program = re.compile(pattern.replace("*", ".*"))
    if program.match(item):
        return True
    return False


class Doer(Thread):
    def __init__(self, component, index, threads, environment, pattern, trigger_all):
        super(Doer, self).__init__()
        self.component = component
        self.item = component["name"]
        self.threads = threads
        self.index = index
        self.environment = environment
        self.pattern = pattern
        self.error = False
        self.success = False
        self.trigger_all = trigger_all

    def run(self):
        for thread in self.component["ancestors"]:
            if thread in self.threads:
                self.threads[thread].join()
                if not self.threads[thread].success:
                    print("Aborting due to upstream error (from {})".format(self.item))
                    return

        if matcher(self.item, self.pattern):
            print("Running {}".format(self.item))
            handle = do_work(self.environment, self.index, self.item, self.trigger_all)

            if handle:
                handle.join()
                self.success = handle.success
            else:
                self.success = True


class Grouper(Thread):
    def __init__(self, run_groups, doer_cache, environment, pattern, trigger_all):
        super(Grouper, self).__init__()
        self.run_groups = run_groups
        self.doer_cache = doer_cache
        self.environment = environment
        self.pattern = pattern
        self.trigger_all = trigger_all


    def run(self):
        doers = []
        for index, group in enumerate(self.run_groups):
            if group in doer_cache:
                doer_cache[group].join()
            else:
                print("Group", group)
                doer = Doer(group, index, doer_cache, self.environment, self.pattern, self.trigger_all)
                doer_cache[group] = doer
                doers.append(doer)
                doer.start()

        for index, doer in enumerate(doers):
            doer.join()

def should_run(rebuild, item):
    for forced in rebuild:
        if item.startswith(forced):
            return True
    return False

def do_work(environment, index, item, trigger_all):
     os.chdir(project_directory)
     if args.only and item not in args.only:
         print("Skipping {}".format(item))
         return

     provider, component, command, manual, local = parse_reference(item)
     if command == "package" and ordered_environments.index(environment) > 0:
         print("Skipping package step")


     if not is_running(item):
         provider, component, command, manual, local = parse_reference(item)

         builds, last_build_status, next_build = get_builds(environment,
            provider, component, command)
         last_successful = find_last_successful_build(builds)

         if manual:
            if not should_run(args.rebuild, item):
                print("Skipping manual build {}".format(item))
                remove_from_running(item, environment)
                return

         component_paths_script = os.path.join(provider, "component-paths")
         if not trigger_all and not args.force and last_successful and os.path.isfile(component_paths_script):

            component_paths_output = run(["./component-paths", environment, component],
                cwd=os.path.join(project_directory, provider), stdout=PIPE).stdout.decode('utf-8').strip()
            component_paths = component_paths_output.split("\n")

            last_run_path = get_last_run_path(environment, provider, component, command)

            if os.path.isfile(last_run_path):
                find_command = ["find"] + component_paths + ["(", "-path", "*.state", "-o", "-path",
                "*.terraform", ")", "-prune", "-o", "-newer", os.path.abspath(last_run_path), "-print"]
                # print(" ".join(find_command))
                changed_files = run(find_command,
                    cwd=os.path.join(project_directory, provider),
                    stdout=PIPE).stdout.decode('utf-8').split("\n")
                changed_files.pop()
                print(changed_files)
                if global_commands.index(command) != 0 and len(changed_files) == 0:
                    print("Component {}/{} is up-to-date".format(component, command))
                    state["notifications"].insert(0, {
                        "variant": "success",
                        "id": time.time(),
                        "title": "{}/{}".format(component, command),
                        "text": "Component is already up-to-date."
                    })
                    return


         previous_outputs, previous_outputs_raw = retrieve_outputs(environment, item)
         if not previous_outputs:
             previous_outputs = {}

         hosts = None
         client = None
         worker_index = 0
         if args.workers:
             worker_index = index % len(args.workers)
             hosts = args.workers[worker_index]

         if args.discover_workers_from_output and args.discover_workers_from_output in previous_outputs_raw:
            available_workers = previous_outputs_raw[args.discover_workers_from_output]
            worker_index = index % len(previous_outputs_raw[args.discover_workers_from_output])
            hosts = available_workers[worker_index]
            print("Decided to use worker {}".format(hosts))

         pipeline_position = global_commands.index(command)
         if pipeline_position == 0:
             os.chdir(project_directory)
             artifacts_path = os.path.abspath(os.path.join(project_directory, "builds/artifacts"))
             destination = "{}.{}.{}.{}.tgz".format(environment, provider, component, next_build)
             # package for a build
             source = provider
             archive = "{}".format(os.path.join(artifacts_path, destination))
             package = Popen(["tar", "chvzf", archive, source],
                stdout=open('tarout', 'w'))
             package.communicate()
             work_dir = project_directory


         else:
             # unpack last artifacts
             environment_position = ordered_environments.index(environment)
             last_environment = environment_position - 1
             artifact_environment = environment
             use_previous_environment_package = False
             if last_environment >= 0:
                 artifact_environment = ordered_environments[0]
                 print("Artifact environment for {} is {}".format(environment, artifact_environment))
                 use_previous_environment_package = True


             parent_command = "package"
             parent_builds, last_build_status, _ = get_builds(artifact_environment, provider, component, parent_command)
             last_successful_build = find_last_successful_build(parent_builds)
             if not last_successful_build:
                return
             print(last_successful_build["build_number"])

             artifacts_path = os.path.abspath("builds/artifacts")
             last_successful_build_number = last_successful_build["build_number"]

             last_artifact_name = "{}.{}.{}.{}.tgz".format(artifact_environment, provider, component, last_successful_build_number)
             source_artifact = os.path.abspath(os.path.join("builds/artifacts", last_artifact_name))

             print("Last artifact name {} used for {}".format(last_artifact_name, environment))
             work_dir_name = "{}_{}_{}_{}_{}".format(environment, provider, component, command, next_build)
             work_dir_path = os.path.abspath(os.path.join("builds/work", work_dir_name))
             if not os.path.isdir(work_dir_path):
                 os.makedirs(work_dir_path)

             unpack = Popen(["tar", "xvf", "{}".format(os.path.join(source_artifact))], stdout=open('tarout', 'w'), cwd=work_dir_path)

             unpack.communicate()
             work_dir = work_dir_path
             print(work_dir_path)


             if hosts and args.force_local == False and local == False:
                 print("Connecting to remote worker")
                 accept_keys_command = Popen(["bash", "-c", "ssh-keyscan -H {}".format(hosts)], stdout=PIPE, stderr=PIPE) # " >> ~/.ssh/known_hosts".format(hosts)])
                 keyout, keyerr = accept_keys_command.communicate()
                 keyout_data = keyout.decode('utf8')
                 known_hosts_file = open("/home/{}/.ssh/known_hosts".format(os.environ["USER"])).read()
                 if keyout_data not in known_hosts_file:
                     Popen(["bash", "-c", "echo \"{}\" >> ~/.ssh/known_hosts".format(keyout_data)])

                 client = ParallelSSHClient([hosts], user=args.workers_user, pkey=args.workers_key[worker_index % len(args.workers_key)])
                 artifact_test = client.run_command("test -f {}".format(last_artifact_name))
                 client.join(artifact_test)
                 if artifact_test[hosts]["exit_code"] != 0:
                        print("Uploading {} to workers...".format(source_artifact))
                        rsync_command = "rsync -Pav -e \"ssh -i {}\" {} {}@{}:{}".format(
                           args.workers_key[0],
                           source_artifact,
                           args.workers_user,
                           hosts,
                           last_artifact_name)
                        print(rsync_command)
                        rsync = Popen(["bash", "-c", rsync_command])
                        rsync.communicate()



                     #cmds = client.scp_send(source_artifact, last_artifact_name)
                     #joinall(cmds, raise_error=True)


         if args.force_local == False and local == False and client != None:
             print("Running SSH build of {}".format(item))
             handle = run_worker_build(client,
                hosts, last_artifact_name,
                next_build,
                environment,
                item,
                provider,
                component,
                command,
                previous_outputs,
                builds)
             os.chdir(project_directory)


         else:
             print("Running local build")
             handle = run_build(
               work_dir,
               next_build,
               environment,
               item,
               provider,
               component,
               command,
               previous_outputs,
               builds)
             os.chdir(project_directory)
         return handle

global_commands = ["package", "validate", "plan", "run", "test", "publish"]

dot_graph = read_dot(args.file)
environment_graph = read_dot(args.environments)
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
components = set()

for item in ordering:
    provider, component, command, manual, local = parse_reference(item)
    components.add("{}/{}".format(provider, component))

events = []


for index, environment in enumerate(ordered_environments):
    for component in components:
        state["components"].append({
            "name": component,
            "status": "ready",
            "command": "validate",
            "environment": environment
        })
        latest = {
            "name": component,
            "environment": environment,
            "commands": []
        }
        state["latest"].append(latest)
        for command in global_commands:
            if index > 0 and command == "package":
                continue # skip packaging for later environments
            latest["commands"].append({
                "name": command,
                "environment": environment,
                "progress": 0,
                "buildIdentifier": "0"
            })




def is_running(reference):
  for item in state["running"]:
      if item["reference"] == reference:
        return True
  return False

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'secret!'

@app.route('/environments')
def environments():
  environments = run(["dot", "-Tsvg", "environments.dot"], stdout=PIPE).stdout.decode('utf-8').strip()
  return Response(environments, mimetype='image/svg+xml')

@app.route('/architecture')
def architecture():
  architecture = run(["dot", "-Tsvg", "architecture.dot"], stdout=PIPE).stdout.decode('utf-8').strip()
  return Response(architecture, mimetype='image/svg+xml')

@app.route('/')
def index():
  jobs = []

  #for environment in ordered_environments:
    #jobs = jobs + list(map(partial(create_jobs, environment), ordering))

  return render_template('index.html', jobs=[])

@app.route('/json')
def return_json():
  for environment in state["environments"]:
      environment["status"] = "ready"

  for component in state["components"]:
      component["status"] = "ready"
      component["progress"] = 100
      component["build_success"] = "success"

  for item in state["running"]:
      provider, running_component, command, manual, local = parse_reference(item["reference"])


      if "log_file" in item:
          item["current_size"] = os.stat(item["log_file"]).st_size
          if item["last_size"] != 0:
              item["progress"] = (item["current_size"] / item["last_size"]) * 100

              for environment in state["environments"]:
                  if item["environment"] == environment["name"]:
                      environment["status"] = "running"

              for component in state["components"]:

                  component_provider, component_name = component["name"].split("/")
                  if item["environment"] == component["environment"] and component_provider == provider and running_component == component_name:
                      component["status"] = "running"
                      component["progress"] = item["progress"]

              for latest in state["latest"]:
                  if latest["environment"] == item["environment"] and latest["name"] == "{}/{}".format(provider, running_component):
                      for current_command in latest["commands"]:
                          if current_command["name"] == command:
                              current_command["progress"] = item["progress"]


  state["running"] = sorted(state["running"], key=lambda item: item["reference"])

  for component_data in state["latest"]:
      provider, component = component_data["name"].split("/")
      component_data["build_success"] = "success"
      for command_data in component_data["commands"]:
          command = command_data["name"]
          builds, last_build_status, next_build = get_builds(component_data["environment"], provider, component, command)

          if builds:
              current_build = builds[-1]
              command_data["build_number"] = current_build["build_number"]
              command_data["build_success"] = "success" if last_build_status else "failure"

              if not last_build_status:
                  component_data["build_success"] = "failure"


              if not command_data.get("progress"):
                  command_data["progress"] = 100

  for component in state["components"]:
      for component_data in state["latest"]:
          if component_data["environment"] == component["environment"] and component_data["name"] == component["name"] and component_data["build_success"] == "failure":
              component["build_success"] = "failure"

  for environment in state["environments"]:
      environment["build_success"] = "success"
      for latest in state["latest"]:
          if latest["environment"] == environment["name"] and latest["build_success"] == "failure":
              environment["build_success"] = "failure"


  q = request.args.get("q") or ""
  if q != last_q["q"]:
      state["searchResults"] = {
        "environments": list(map(lambda x: x["name"], filter(lambda x: q in x["name"], state["environments"]))),
        "components": list(map(lambda x: x, filter(lambda x: q in x["name"], state["components"])))
      }
      last_q["q"] = q

  return Response(json.dumps(state), content_type="application/json")

from flask import request
@app.route('/logs', methods=["POST"])
def retrieve_logs():
    data = request.get_json()
    print(data["environment"])
    component_reference = data["component"]["name"]
    provider, component = component_reference.split("/")
    command = data["command"]["name"]
    builds, last_build_status, next_build = get_builds(data["environment"], provider, component, command)

    build = builds[-1]

    log_data = open(build["log_file"]).read()

    logs = {
        "console": log_data
    }
    print("Retrieving logs {}".format(component_reference))
    return Response(json.dumps(logs), content_type="application/json")

@app.route('/force-trigger', methods=["POST"])
def triggerForce():
  data = request.get_json()
  print("Triggering {}".format(data["name"]))
  for component in state["components"]:
      if component["name"] == data["name"]:
          component["status"] = "queued"
  environment = data["environment"]
  provider, component, command, manual, local = parse_reference(data["name"] + "/run")
  last_run_file = get_last_run_path(environment, provider, component, command)
  if os.path.exists(last_run_file):
      os.remove(last_run_file)
  begin_pipeline(environment, streams, orderings, data["name"])
  return Response(headers={'Content-Type': 'application/json'})


@app.route('/trigger', methods=["POST"])
def trigger():
  data = request.get_json()
  print("Triggering {}".format(data["name"]))
  for component in state["components"]:
      if component["name"] == data["name"]:
          component["status"] = "queued"
  environment = data["environment"]
  trigger_all = data.get("force", False)
  propagate = not trigger_all
  if trigger_all:
      print("Build is forced")
  begin_pipeline(environment, streams, orderings, data["name"], propagate=propagate, trigger_all=trigger_all)
  return Response(headers={'Content-Type': 'application/json'})

@app.route('/propagate', methods=["POST"])
def propagate():
  data = request.get_json()
  print("Propagating changes {}".format(data["name"]))
  environment = data["environment"]
  begin_pipeline(environment, streams, orderings, "{}/package".format(data["name"]))
  begin_pipeline(environment, streams, orderings, "{}/test".format(data["name"]))
  need_testing = G.successors("{}/publish".format(data["name"]))
  for successor in need_testing:
      print("{} needs testing due to change to {}".format(successor, data["name"]))
  return Response(headers={'Content-Type': 'application/json'})

@app.route('/validate', methods=["POST"])
def validate():
  data = request.get_json()
  print("Validating stack {}".format(data["name"]))
  environment = data["name"]
  begin_pipeline(environment, streams, orderings, "*/*/validate")

  return Response(headers={'Content-Type': 'application/json'})



@app.route('/trigger-environment', methods=["POST"])
def triggerEnvironment():
  data = request.get_json()
  pprint(data)
  trigger_all = data["forced"]
  begin_pipeline(data["environment"], streams, orderings, "", trigger_all=trigger_all)
  return Response(headers={'Content-Type': 'application/json'})

@app.route('/running')
def event_json():
  event_response = Response(json.dumps(state["running"]), content_type="application/json")
  return event_response


import re

head = run(["git", "rev-parse", "HEAD"], stdout=PIPE).stdout.decode('utf-8').strip()

def write(data):
    stdout.write(data)

component_folders = {
"chef": "applications",
"terraform": "components",
"packer": None,
"shell": None,
}

component_files = {
  "packer": lambda provider, component: "{}/{}.json".format(provider, component)
}

def build_info(environment, provider, component):
  return "pipeline/{}/{}/{}/*".format(environment, provider, component)

def pending_build_info(environment, provider, component):
  return "pipeline/pending/{}/{}/{}/*".format(environment, provider, component)

def sorted_nicely( l ):
  """ Sort the given iterable in the way that humans expect."""
  convert = lambda text: int(text) if text.isdigit() else text
  alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key) ]
  return sorted(l, key = alphanum_key)



def has_plumbing_changed(provider, component, last_build):
  if not last_build:
    return True
  provider_query = ["git", "diff", "--exit-code", last_build, head, "--", "run"]
  provider_changes = run(provider_query, cwd=provider, stdout=PIPE)
  return provider_changes.returncode != 0

def has_component_changed(provider, component, last_build):
  if not last_build:
    return True
  component_folder = component_folders[provider]
  component_folder_changed = False
  provider_folder_changed = False
  component_file_changed = False

  if component_folder:
      component_query = ["git", "diff", "--exit-code", last_build, head, "--", "/".join([component_folder, component])]
      component_changes = run(component_query, stdout=PIPE)
      print(" ".join(component_query))
      component_folder_changed = component_changes.returncode != 0

  if provider in component_files:
      component_query = ["git", "diff", "--exit-code", last_build, head, "--", component_files[provider](provider, component)]
      component_changes = run(component_query, cwd=provider, stdout=PIPE)
      print(" ".join(component_query))
      component_file_changed = component_changes.returncode != 0

  component_query = ["git", "diff", "--exit-code", last_build, head,  "--", provider]
  component_changes = run(component_query, stdout=PIPE)
  provider_folder_changed = component_changes.returncode != 0
  return component_folder_changed or component_file_changed or provider_folder_changed

# pprint(dot_graph.nodes(data=True))
from networkx.algorithms.traversal.depth_first_search import dfs_successors
from networkx.algorithms.traversal.depth_first_search import dfs_predecessors
from networkx.algorithms.traversal.breadth_first_search import bfs_predecessors
from networkx.algorithms.dag import ancestors
import itertools


# [G.nodes[dependency].get('ran', False) for dependency in G.predecessors(node)]

class BuildFailure(Exception):
    pass

def expand_secrets(path, previous, current):
    for k, v in current.items():
        if isinstance(v, dict):
            expand_secrets(path + "." + k, previous, v)
        else:
            previous[path + "." + k] = v
    return previous

def construct_environment(work_directory, build_number, environment, provider, component, command, previous_outputs):
    env = {
        "OUTPUT_PATH": os.path.join(work_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command)),
        "EXIT_CODE_PATH": get_exit_code_path(work_directory, environment, provider, component, command, build_number),
        "ARTIFACT_PATH": os.path.join(work_directory, "builds/published/{}.{}.{}.{}.{}.tgz".format(environment, provider, component, command, build_number))
    }
    env.update(previous_outputs)
    if "secrets" in env:
        expand_secrets("secrets", env, env["secrets"])
        del env["secrets"]
    env["BUILD_NUMBER"] = str(build_number)
    env["ENVIRONMENT"] = str(environment)
    return env

def run_worker_build(client,
    host,
    artifact,
    build_number,
    environment,
    dependency,
    provider,
    component,
    command,
    previous_outputs,
    builds):
    class Worker(Thread):
        def run(self):
            self.success = False
            exit_code_path = get_exit_code_path(project_directory, environment, provider, component, command, build_number)
            if os.path.exists(exit_code_path):
                os.remove(exit_code_path)
            self.error = False
            lock.acquire()
            builds_filename = get_builds_filename(environment, provider, component, command)
            ensure_file(builds_filename)
            build_data = json.loads(open(builds_filename).read())
            this_build = {
                "success": False,
                "remote": True,
                "build_number": build_number,
                "reference": dependency,
                "status": "running",
                "environment": environment
            }
            state["running"].append(this_build)
            mark_dependency_as_running(dependency, environment)
            build_data["builds"].append(this_build)
            write_builds_file(builds_filename, build_data)
            lock.release()
            last_successful_build = find_last_successful_build(builds)
            if last_successful_build:
                try:
                    last_logfile = "builds/logs/{:03d}-{}-{}-{}-{}.log".format(last_successful_build["build_number"],
                        environment,
                        provider, component,
                        command)

                    last_size = os.stat(last_logfile).st_size
                    this_build["last_size"] = last_size
                    this_build["log_file"] = log_filename
                except Exception as e:
                    pass


            print("Creating remote directories")
            work_directory = "builds"
            cmd = client.run_command("mkdir -p builds/exits")
            client.join(cmd)
            cmd = client.run_command("mkdir -p builds/outputs")
            client.join(cmd)
            cmd = client.run_command("mkdir -p builds/envs")
            client.join(cmd)
            cmd = client.run_command("mkdir -p builds/logs")
            client.join(cmd)
            cmd = client.run_command("mkdir -p builds/published")
            client.join(cmd)


            env = construct_environment("", build_number, environment, provider, component, command, previous_outputs)
            work_path = "builds/work/{}.{}.{}.{}".format(environment, provider, component, command)
            make_work_path = client.run_command("mkdir -p {}".format(work_path))
            client.join(make_work_path)

            print("Unpacking artifact remotely")
            unpack_command = "tar -xvf {} -C {}".format(artifact, work_path)

            extract = client.run_command(unpack_command)
            client.join(extract)
            env_file_name = "{}.{}.{}.{}.{}".format(environment, provider, component, command, build_number)
            env_file_path = os.path.join(project_directory, "builds/envs/", env_file_name)
            env_file = open(env_file_path, "w")
            for key, value in env.items():
                escaped_value = value
                if " " in value:
                    escaped_value = "\"" + value + "\""
                env_file.write("{}={}".format(key, escaped_value))

                env_file.write("\n")
            env_file.flush()
            env_file.close()
            print("Sending envs file to worker")
            remote_env_path = os.path.join("builds/envs", env_file_name)
            cmds = client.scp_send(env_file_path, remote_env_path, True)
            joinall(cmds, raise_error=True)
            ran_remotely = False
            build_stdout = None
            build_stderr = None
            test_command = "test -f {}/{}/{}".format(work_path, provider, command)
            print(test_command)
            print(work_path)
            test_exists = client.run_command(test_command)
            client.join(test_exists)

            print("Running require")
            chosen_file = run_require("", environment, provider, component, command)
            if chosen_file:
                 print(chosen_file)
                 destination_path = os.path.join(work_path, os.path.basename(chosen_file))
                 print("Copying {} to remote {}".format(chosen_file, destination_path))

                 # cmds = client.scp_send(chosen_file, destination_path, True)
                 # joinall(cmds, raise_error=True)
                 rsync_command = "rsync -Pav -e \"ssh -i {}\" {} {}@{}:{}".format(
                    args.workers_key[0],
                    chosen_file,
                    args.workers_user,
                    host,
                    destination_path)
                 print(rsync_command)
                 rsync = Popen(["bash", "-c", rsync_command])
                 rsync.communicate()

                 unzip_command = "cd {} ; tar -xf {}".format(work_path, os.path.basename(chosen_file))
                 unzip_artifact = client.run_command(unzip_command)
                 print(unzip_command)
                 client.join(unzip_artifact)


            if test_exists[host]["exit_code"] == 0:
                print("Running build remotely")
                ran_remotely = True
                remote_log_filename = "builds/logs/{}-{}.{}.{}.{}.log".format(build_number, environment, provider, component, command)
                build_command = client.run_command("""set -a ;
                    source {} ;
                    export OUTPUT_PATH=$(readlink -f ${{OUTPUT_PATH}}) ;
                    export EXIT_CODE_PATH=$(readlink -f ${{EXIT_CODE_PATH}}) ;
                    export ARTIFACT_PATH=$(readlink -f ${{ARTIFACT_PATH}}) ;
                    cd {}/{} ;
                    ./{} {} {}""".format(remote_env_path, work_path, provider, command, environment, component, remote_log_filename))

            else:
                lock.acquire()
                builds_filename = get_builds_filename(environment, provider, component, command)
                ensure_file(builds_filename)
                build_data = json.loads(open(builds_filename).read())
                this_build = build_data["builds"][-1]
                print("Not implemented")
                this_build["success"] = True
                self.success = True
                open(os.path.join(project_directory,
                    "builds/outputs/{}.{}.{}.{}.outputs.json"
                    .format(environment, provider, component, command)), 'w').write("{}")
                write_builds_file(builds_filename, build_data)
                lock.release()
                remove_from_running(dependency, environment)
                open(os.path.join(get_last_run_path(environment, provider, component, command)), 'w').write(':)')
                return
            if ran_remotely:
                print("Setting up logs...")
                logfile = open("builds/logs/{}-{}.{}.{}.{}.log".format(build_number, environment, provider, component, command), "w")

                client.join(build_command)
                for line in build_command[host]["stdout"]:
                     logfile.write(line + "\n")
                for line in build_command[host]["stderr"]:
                    logfile.write(line + "\n")
                print("Remote build finished")
                remove_from_running(dependency, environment)

                print("Downloading outputs...")
                dest_output = os.path.join(project_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command))

                receive_outputs = client.copy_remote_file(os.path.join("builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command)), dest_output)

                joinall(receive_outputs)
                os.rename("{}_{}".format(dest_output, host), dest_output)

                print("Downloading exit code...")
                dest_exit_code = os.path.join(project_directory, "builds/exits/{}.{}.{}.{}.{}.exitcode".format(environment, provider, component, command, build_number))
                receive_exit_code = client.copy_remote_file(os.path.join("builds/exits/{}.{}.{}.{}.{}.exitcode".format(environment, provider, component, command, build_number)), dest_exit_code)

                joinall(receive_exit_code, raise_error=True)
                os.rename("{}_{}".format(dest_exit_code, host), dest_exit_code)

                print("Downloading artifact...")
                check_for_artifacts = client.run_command("test -f {}".format("builds/published/{}.{}.{}.{}.{}.tgz".format(environment, provider, component, command, build_number)))
                client.join(check_for_artifacts)

                if check_for_artifacts[host]["exit_code"] == 0:
                    dest_artifact = os.path.join(project_directory, "builds/published/{}.{}.{}.{}.{}.tgz".format(environment, provider, component, command, build_number))
                    receive_artifact = client.copy_remote_file(os.path.join("builds/published/{}.{}.{}.{}.{}.tgz".format(environment, provider, component, command, build_number)), dest_artifact)
                    joinall(receive_artifact, raise_error=True)
                    os.rename("{}_{}".format(dest_artifact, host), dest_artifact)

                last_running_build = Component(dependency, environment, provider, component, command, args).calculate_state()
                if last_running_build:
                    self.success = last_running_build["success"]

    worker = Worker()
    worker.start()
    return worker

# Find artifact file
def run_require(work_dir, environment, provider, component, command):

    if os.path.isfile(os.path.join(work_dir, provider, "require")) and command == "run":
        require = Popen(["./require",
         environment,
         component], cwd=os.path.join(work_dir, provider), stdin=sys.stdin, stdout=PIPE, stderr=sys.stderr)
        require_stdout, require_stderr = require.communicate()
        lines = require_stdout.decode('utf-8').split("\n")
        lines.pop()
        for requirement in lines:
            requirement_name, specification = requirement.split(" ")
            requirement_provider, requirement_component = requirement_name.split("/")
            print(requirement_name)
            print(specification)
            dependencies = Popen(["bash", "-c", "find builds/published  -printf \"%T+\t%p\n\" | sort -r"], stdout=PIPE)
            sorted, dep_errors = dependencies.communicate()
            available = sorted.decode('utf-8').split("\n")
            available.pop()
            match = "{}\.{}\.{}\.{}\..*\.tgz".format(environment, requirement_provider, requirement_component, "run")
            chosen_file = None
            for availability in available:
                times, file = availability.split("\t")
                # we found a file that matched what we're looking for
                if re.match(match, file.split("/")[-1]):
                    if specification == "latest":
                        chosen_file = file
                        break
                    elif specification == "latestSuccessful":
                        builds_filename = get_builds_filename(environment, requirement_provider, requirement_component, "run")
                        ensure_file(builds_filename)
                        build_data = json.loads(open(builds_filename).read())
                        for build in reversed(build_data["builds"]):
                            print(file.split(".")[4])
                            if build["success"] == True and \
                              build["reference"].endswith("{}/{}/{}".format(requirement_provider, requirement_component, "run")) \
                              and build["build_number"] == int(file.split(".")[4]):
                                chosen_file = file
                                break
                        if chosen_file:
                            break
            # copy chosen_file
            if chosen_file:
                return chosen_file

def run_build(work_dir,
    build_number,
    environment,
    dependency,
    provider,
    component,
    command,
    previous_outputs,
    builds):


    provider, component, command, manual, local = parse_reference(dependency)
    log_filename = "builds/logs/{:03d}-{}-{}-{}-{}.log".format(build_number, environment, provider, component, command)
    log_file = open(os.path.join(project_directory, log_filename), 'w')
    env = construct_environment(project_directory, build_number, environment, provider, component, command, previous_outputs)
    env["OUTPUT_PATH"] = os.path.abspath(env["OUTPUT_PATH"])
    env["EXIT_CODE_PATH"] = os.path.abspath(env["EXIT_CODE_PATH"])
    env["ARTIFACT_PATH"] = os.path.abspath(env["ARTIFACT_PATH"])
    pretty_build_number = get_pretty_build_number(build_number)
    lock.acquire()
    builds_filename = get_builds_filename(environment, provider, component, command)
    ensure_file(builds_filename)
    build_data = json.loads(open(builds_filename).read())
    this_build = {
        "success": False,
        "build_number": build_number,
        "reference": dependency,
        "status": "running",
        "environment": environment
    }
    state["running"].append(this_build)
    mark_dependency_as_running(dependency, environment)
    last_successful_build = find_last_successful_build(builds)
    if last_successful_build:
        try:
            last_logfile = "builds/logs/{:03d}-{}-{}-{}-{}.log".format(last_successful_build["build_number"],
                environment,
                provider, component,
                command)

            last_size = os.stat(last_logfile).st_size
            this_build["last_size"] = last_size
            this_build["log_file"] = log_filename
        except Exception as e:
            print(e)
    build_data["builds"].append(this_build)
    write_builds_file(builds_filename, build_data)
    lock.release()
# tag pending before build
# run(["git", "tag", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component,
#    pretty_build_number)], stdout=PIPE)


    class CommandRunner(Thread):
        def run(self):
          self.error = False
          self.success = False
          exit_code_path = get_exit_code_path(project_directory, environment, provider, component, command, build_number)
          if os.path.exists(exit_code_path):
              os.remove(exit_code_path)

          builds_filename = get_builds_filename(environment, provider, component, command)
          ensure_file(builds_filename)
          build_data = json.loads(open(builds_filename).read())
          this_build = build_data["builds"][-1]

          if not os.path.isfile(os.path.join(provider, command)):
            builds_filename = get_builds_filename(environment, provider, component, command)
            ensure_file(builds_filename)
            build_data = json.loads(open(builds_filename).read())
            this_build = build_data["builds"][-1]
            self.success = True
            this_build["success"] = True
            lock.acquire()
            open("builds/outputs/{}-{}-{}.json".format(provider, component, command), 'w').write("{}")
            write_builds_file(builds_filename, build_data)
            remove_from_running(dependency, environment)
            lock.release()
            open(os.path.join(get_last_run_path(environment, provider, component, command)), 'w').write(':)')
            return

          #if args.rebuild and dependency not in args.rebuild:
        #      print("Skipping due to rebuild")
        #      return
          environment_filename = os.path.join(project_directory, "builds/environments/{}-{}-{}-{}.env".format(environment, provider, component, command))
          environment_file = open(environment_filename, 'w')
          environment_file.write(json.dumps(env, indent=4))


          print("Running require")
          chosen_file = run_require(work_dir, environment, provider, component, command)
          if chosen_file:
              print(chosen_file)
              print("Copying required file...")
              copy(chosen_file, os.path.join(work_dir))
              extract_dependency = Popen(["tar", "xf", os.path.join(work_dir, os.path.basename(chosen_file)), "-C", work_dir])
              extract_dependency.communicate()

          env["USER"] = getpass.getuser()
          pprint(env)

          print(os.path.join(work_dir, provider))
          runner = Popen(["./" + command,
             environment,
             component], cwd=os.path.join(work_dir, provider), stdin=sys.stdin, stdout=log_file, stderr=log_file,
             env=env)


          this_build["pid"] = runner.pid
          lock.acquire()
          write_builds_file(builds_filename, build_data)
          lock.release()
          print("{}".format(log_file.name))
          runner.communicate(input=None, timeout=None)
          runner.wait(timeout=None)

      # outputs = result.decode('utf-8')

          if runner.returncode != 0:
            this_build["success"] = False
            del this_build["pid"]
            print("{} {} Build failed {}".format(dependency, pretty_build_number, runner.returncode))
            self.error = True
            lock.acquire()
            write_builds_file(builds_filename, build_data)
            lock.release()
            remove_from_running(dependency, environment)
            return

          last_running_build = Component(dependency, environment, provider, component, command, args).calculate_state()
          if last_running_build:
              self.success = last_running_build["success"]



    worker_thread = CommandRunner()
    worker_thread.start()
    return worker_thread

def find_last_successful_build(builds):
    for build in reversed(builds):

      if build["success"] == True:
          return build
    return None

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

def create_jobs(environment, build):
    provider, component, command, manual, local = parse_reference(build)
    tags, last_build_status, next_build = get_builds(environment, provider, component, command)

    if last_build_status:
      status = "green"
    else:
      status = "red"
    return {
      "status": status,
      "environment": environment,
      "name": "{}".format(build),
      "last_success": "",
      "last_failure": "",
      "last_duration": ""
    }



def apply_pattern(pattern, items):
    return list(filter(matcher, items))



def begin_pipeline(environment, streams, orderings, pattern, propagate=True, trigger_all=False):
    class Streams(Thread):
        def __init__(self, environment, trigger_all, propagate):
            super(Streams, self).__init__()
            self.environment = environment
            self.trigger_all = trigger_all
            self.propagate = propagate

        def run(self):

            threads = {}

            for index, component in enumerate(streams):
                # component, index, threads, environment, pattern

                if matcher(component["name"], pattern):
                    new_thread = Doer(component, index, threads, self.environment, pattern, self.trigger_all)
                    threads[component["name"]] = new_thread

            for index in sorted(orderings):
                for component in orderings[index]:
                    if matcher(component, pattern):
                        threads[component].start()

            # Wait for workers to finish
            for thread in threads.values():
                thread.join()

            if propagate:
                # environment has finished, start the next environment
                current_environment = ordered_environments.index(self.environment)
                next_environment = current_environment + 1
                if len(ordered_environments) > next_environment:
                    stream_run = Streams(ordered_environments[next_environment], self.trigger_all, self.propagate)
                    stream_run.start()


    stream_run = Streams(environment, trigger_all, propagate)
    stream_run.start()




finished_builds = {}
parent = None
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
from component_scheduler import scheduler
loaded = open("builds/loaded", "w")
pprint(loaded_components, stream=loaded)
print("Scheduling components into run groups...")
streams, orderings = scheduler.parallelise_components(loaded_components)

state["parallelism"] = orderings
loaded_json_file = open("builds/loaded.json", "w")
loaded_json_file.write(json.dumps(loaded_components, indent=4))
loaded_json_file.flush()
loaded_json_file.close()

pprint(streams)
stream_file = open("builds/run_groups", "w")
pprint(streams, stream=stream_file)
stream_file.flush()
stream_file.close()

pprint(streams)
parallelism_file = open("builds/parallelism", "w")
pprint(orderings, stream=parallelism_file)
parallelism_file.flush()
parallelism_file.close()

print("Scheduling finished... Loading...")
for environment in list(ordered_environments):
  state["environments"].append({
    "name": environment,
    "progress": 100,
    "status": "ready",
    "facts": "{} tasks, {} components"
        .format(len(streams),
        len(list(filter(lambda x : x["environment"] == environment, state["components"]))))
  })

  # find running processes from last run
  for item in ordering:
      provider, component, command, manual, local = parse_reference(item)
      Component(item, args.environment, provider, component, command, args).calculate_state()


  for node in ordering:
      provider, component, command, manual, local = parse_reference(node)
      builds, last_success, next_build = get_builds(args.environment, provider, component, command)
      for build in builds:
          if build["status"] == "running":
              state["running"].append(build)
