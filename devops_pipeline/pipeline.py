#!/usr/bin/env python3
from threading import Thread
from functools import reduce
import collections

from functools import partial
from flask import Flask, render_template, Response
from flask_socketio import SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

import os
cwd = os.getcwd()
print(cwd)

import psutil
from argparse import ArgumentParser
from networkx.drawing.nx_pydot import read_dot, write_dot
from networkx.readwrite import json_graph
import networkx as nx
import sys, json

import sys
dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.append(dir_path)

from sys import stdout
from pprint import pprint
from subprocess import Popen, PIPE, run, call

run_groups = []
job_monitors = {}

def parse_reference(reference):
  provider, component_name, command = reference.split("/")
  component = component_name.replace("*","")
  return provider, component, command, "*" in component_name

def render_pipeline(run_groups):
  group_count = 1
  for index, group in enumerate(run_groups):
      print("{}/{} Group".format(index + 1, len(run_groups)))
      for item in group:
          print("{}".format(item))
      print("")
      step_outputs = retrieve_outputs(environment, item)
      print(step_outputs)


def main():

    parser = ArgumentParser(description="devops-pipeline")
    parser.add_argument("environment")
    parser.add_argument("--file", default="architecture.dot")
    parser.add_argument("--keys", nargs="+", default=[] )
    parser.add_argument("--gui", action="store_true" )
    parser.add_argument("--force", action="store_true" )
    parser.add_argument("--only", nargs='+', default=[])
    parser.add_argument("--ignore", nargs='+', default=[] )
    parser.add_argument("--rebuild", nargs='+', default=[])
    parser.add_argument("--manual", nargs='+', default=[])
    parser.add_argument("--no-trigger", action="store_true", default=False)

    args = parser.parse_args()
    global_commands = ["validate", "plan", "run", "test", "publish"]

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
            G.add_edge(parent, "{}/{}".format(node, "validate"))
        for children in G.successors(node):
            G.add_edge("{}/{}".format(node, "publish"), children)
        dot_graph.remove_node(node)

    tree = nx.topological_sort(dot_graph)
    ordered_environments = nx.topological_sort(environment_graph)

    write_dot(dot_graph, "architecture.expanded.dot")

    ordering = list(tree)
    components = set()

    for item in ordering:
        provider, component, command, manual = parse_reference(item)
        components.add("{}/{}".format(provider, component))

    events = []
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
    }]
    }
    for component in components:
        state["components"].append({
            "name": component,
            "status": "green",
            "command": "plan"
        })
        latest = {
            "name": component,
            "commands": []
        }
        state["latest"].append(latest)
        for command in global_commands:
            latest["commands"].append({
                "name": command,
                "progress": 0,
                "buildIdentifier": "0"
            })



    def is_running(reference):
      for item in state["running"]:
          if item["reference"] == reference:
            return True
      return False

    def remove_from_running(reference):
      for item in state["running"]:
          if item["reference"] == reference:
            state["running"].remove(item)

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
      for item in state["running"]:
          if "log_file" in item:
              item["current_size"] = os.stat(item["log_file"]).st_size
              if item["last_size"] != 0:
                  item["progress"] = (item["current_size"] / item["last_size"]) * 100
      return Response(json.dumps(state), content_type="application/json")

    from flask import request
    @app.route('/trigger', methods=["POST"])
    def trigger():
      data = request.get_json()
      begin_pipeline(args.environment, run_groups, data["name"])
      return Response(headers={'Content-Type': 'application/json'})


    @app.route('/trigger-environment', methods=["POST"])
    def triggerEnvironment():
      data = request.get_json()
      pprint(data)
      begin_pipeline(data["environment"], run_groups, "")
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

    def get_builds_filename(environment, provider, component, command):
        return "builds/{}.{}.{}.{}.json".format(environment, provider, component, command)

    def ensure_file(build_file):
      if not os.path.isfile(build_file):
          open(build_file, 'w').write(json.dumps({
              "builds": []
          }, indent=4))

    def get_builds(environment, provider, component, command):
        builds_file = get_builds_filename(environment, provider, component, command)
        ensure_file(builds_file)
        build_data = json.loads(open(builds_file).read())
        builds = build_data["builds"]
        if len(builds) == 0:
            last_build_status = False
            next_build = 1
        else:
            last_build_status = builds[-1]["success"]
            next_build = builds[-1]["build_number"] + 1
        return (builds, last_build_status, next_build)

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

    def write_builds_file(builds_filename, builds_data):
        f = open(builds_filename, 'w')
        f.write(json.dumps(builds_data, indent=4))
        f.close()

    def run_build(build_number,
        environment,
        dependency,
        provider,
        component,
        command,
        previous_outputs,
        builds):

        provider, component, command, manual = parse_reference(dependency)
        log_filename = "logs/{:03d}-{}-{}-{}-{}.log".format(build_number, environment, provider, component, command)
        log_file = open(log_filename, 'w')
        env = {}
        env.update(previous_outputs)
        env["BUILD_NUMBER"] = str(build_number)
        env["ENVIRONMENT"] = str(environment)
        pretty_build_number = "{:0>4d}".format(build_number)

        builds_filename = get_builds_filename(environment, provider, component, command)
        ensure_file(builds_filename)
        build_data = json.loads(open(builds_filename).read())
        this_build = {
            "success": False,
            "build_number": build_number,
            "reference": dependency
        }
        state["running"].append(this_build)
        last_successful_build = find_last_successful_build(builds)
        if last_successful_build:
            try:
                last_logfile = "logs/{:03d}-{}-{}-{}-{}.log".format(last_successful_build["build_number"],
                    environment,
                    provider, component,
                    command)

                last_size = os.stat(last_logfile).st_size
                this_build["last_size"] = last_size
                this_build["log_file"] = log_filename
            except Exception as e:
                pass

    # tag pending before build
    # run(["git", "tag", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component,
    #    pretty_build_number)], stdout=PIPE)


        class CommandRunner(Thread):
            def run(self):
              self.error = False

              builds_filename = get_builds_filename(environment, provider, component, command)
              ensure_file(builds_filename)
              build_data = json.loads(open(builds_filename).read())
              this_build = build_data["builds"][-1]

              if not os.path.isfile(os.path.join(provider, command)):
                builds_filename = get_builds_filename(environment, provider, component, command)
                ensure_file(builds_filename)
                build_data = json.loads(open(builds_filename).read())
                this_build = build_data["builds"][-1]
                print("Not implemented")
                build_data["builds"].append(this_build)
                this_build["success"] = True
                open("outputs/{}-{}-{}.json".format(provider, component, command), 'w').write("{}")
                write_builds_file(builds_filename, build_data)
                remove_from_running(dependency)
                return

              #if args.rebuild and dependency not in args.rebuild:
            #      print("Skipping due to rebuild")
            #      return
              pprint(env)
              runner = Popen([command,
                 environment,
                 component], cwd=provider, stdout=log_file, stderr=log_file,
                 env=env)

              this_build["pid"] = runner.pid
              write_builds_file(builds_filename, build_data)

              print("{}".format(log_file.name))
              runner.communicate(input=None, timeout=None)
              runner.wait(timeout=None)

              # outputs = result.decode('utf-8')

              if runner.returncode != 0:
                this_build["success"] = False
                del this_build["pid"]
                print("{} {} Build failed {}".format(dependency, pretty_build_number, runner.returncode))
                self.error = True
                build_data["builds"].append(this_build)
                write_builds_file(builds_filename, build_data)
                remove_from_running(dependency)
                return

              decoded = json.loads(open("outputs/{}-{}-{}.json".format(provider, component, command)).read())

              if 'secrets' in decoded:
                secrets = decoded.pop('secrets')
                recipient_list = list(map(lambda key: ["--recipient", key], args.keys))
                encrypt_command = ["gpg"] + list(itertools.chain(*recipient_list)) + ["--encrypt"]
                print(encrypt_command)
                encrypter = Popen(encrypt_command, stdin=PIPE, stdout=PIPE, stderr=sys.stderr)
                encoder = Popen(["base64", "--wrap=0"], stdin=encrypter.stdout, stdout=PIPE, stderr=sys.stderr)
                encrypter.stdin.write(json.dumps(secrets).encode('utf-8'))
                encrypter.stdin.close()
                encrypted_secrets, err = encoder.communicate()
                decoded["secrets"] = encrypted_secrets.decode('utf-8')

              # Write our outputs to the output bucket
              output_filename = "outputs/{}-{}-{}.json".format(provider, component, command)
              with open(output_filename, 'w') as output_file:
                output_file.write(json.dumps(decoded))
              run(["aws", "s3", "cp", output_filename, "s3://vvv-{}-outputs/{}/{}/{}.json".format(environment, provider, component, pretty_build_number)])

              # env.update(json.loads(outputs))
              # pprint(env)

              print("{} {} Build passed".format(dependency, pretty_build_number))
              # run(["git", "tag", "-d", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)
              run(["git", "tag", "pipeline/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)

              this_build["success"] = True
              build_data["builds"].append(this_build)
              write_builds_file(builds_filename, build_data)


        worker_thread = CommandRunner()
        worker_thread.start()
        return worker_thread

    def find_last_successful_build(builds):
        for build in reversed(builds):

          if build["success"] == True:
              return build
        return None

    def retrieve_outputs(environment, node):
        print("Retrieving outputs of {}".format(node))
        provider, component, command, manual = parse_reference(node)
        parents = list(ancestors(G, node))

        env = {}
        for parent in parents:

          parent_provider, parent_component, parent_command, manual = parse_reference(parent)
          parent_builds, last_build_status, next_build = get_builds(environment, parent_provider, parent_component, parent_command)

          last_successful_build = find_last_successful_build(parent_builds)

          if last_successful_build == None:
              print("No successful build for {}".format(parent))
              continue
          print("Successful build found for {}".format(parent))
          pretty_build_number = "{:0>4d}".format(last_successful_build["build_number"])
          output_filename = "outputs/{}-{}-{}.json".format(parent_provider, parent_component, parent_command)
          if not os.path.isfile(output_filename):
              run(["aws", "s3", "cp", "s3://vvv-{}-outputs/{}/{}/{}.json".format(environment, parent_provider, parent_component, pretty_build_number),
                output_filename])

          loaded_outputs = json.loads(open(output_filename).read())
          if 'secrets' in loaded_outputs:
            decoder = Popen(["base64", "-d", "--wrap=0"], stdin=PIPE, stdout=PIPE, stderr=sys.stderr)
            decrypter = Popen(["gpg", "--decrypt"], stdin=decoder.stdout, stdout=PIPE, stderr=sys.stderr)
            decoder.stdin.write(loaded_outputs['secrets'].encode('utf-8'))
            decoder.stdin.close()
            decrypted_result, err = decrypter.communicate()
            loaded_outputs['secrets'] = json.loads(decrypted_result.decode('utf-8'))
            open(output_filename, 'w').write(json.dumps(loaded_outputs))

          env.update(loaded_outputs)
        return env

    def create_jobs(environment, build):
        provider, component, command, manual = parse_reference(build)
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
        def matcher(item):
            if item.startswith(pattern):
                return True
            if item == pattern:
                return True
            if pattern == "":
                return True
            program = re.compile(pattern.replace("*", ".*"))
            if program.match(item):
                return True
            return False
        return list(filter(matcher, items))

    def begin_pipeline(environment, run_groups, pattern):
      if "monitor" in job_monitors:
          print("Already began")

      class JobMonitor(Thread):
        def run(self):
             self.error = False
             for group in run_groups:
                 if self.error:
                     print("Stopping due to build error")
                     break

                 group_handles = []
                 print("")
                 matched = list(apply_pattern(pattern, group))


                 for item in matched:

                     if args.only and item not in args.only:
                         print("Skipping {}".format(item))
                         continue


                     if not is_running(item):


                         print("Running {}".format(item))
                         provider, component, command, manual = parse_reference(item)

                         builds, last_build_status, next_build = get_builds(environment,
                            provider, component, command)
                         last_successful = find_last_successful_build(builds)

                         if manual and item not in args.rebuild:
                            print("Skipping manual build {}".format(item))
                            remove_from_running(item)
                            continue
                         print("")

                         previous_outputs = retrieve_outputs(environment, item)
                         if not previous_outputs:
                             previous_outputs = {}
                         pprint(previous_outputs)

                         handle = run_build(next_build,
                           environment,
                           item,
                           provider,
                           component,
                           command,
                           previous_outputs,
                           builds)
                         group_handles.append((item, handle))
                     else:
                         print("Already running")


                 # print("Waiting for group to finish... {}".format(group))
                 for node, handle in group_handles:
                     handle.join()
                     print("Group item finished")
                     remove_from_running(node)
                     if handle.error:
                         self.error = True

      job_monitor = JobMonitor()
      job_monitors["monitor"] = job_monitor
      job_monitor.start()




    finished_builds = {}
    parent = None
    loaded_components = []
    for count, node in enumerate(ordering):
        component_ancestors = list(ancestors(G, node))
        successors = list(G.successors(node))
        loaded_components.append({
            "name": node,
            "ancestors": component_ancestors,
            "successors": successors
        })
    from component_scheduler import scheduler
    run_groups = scheduler.parallelise_components(loaded_components)

    for environment in list(ordered_environments):
      state["environments"].append({
        "name": environment,
        "progress": 100,
        "status": "ready",
        "facts": "{} run groups, {} tasks {} components"
            .format(len(run_groups),
            reduce(lambda previous, current: previous + len(current), run_groups, 0),
            len(state["components"]))
      })

      # find running processes from last run

      for node in ordering:
          provider, component, command, manual = parse_reference(node)
          builds, last_success, next_build = get_builds(args.environment, provider, component, command)
          for build in builds:
              if "pid" in build and psutil.pid_exists(build["pid"]):
                  state["running"].append(build)


    if args.gui:
        app.run()
    else:
        begin_pipeline(args.environment, run_groups, "")






if __name__ == '__main__':
  main()
