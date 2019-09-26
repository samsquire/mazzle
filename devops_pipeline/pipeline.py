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
project_directory = os.getcwd()

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

def get_last_run_path(environment, provider, component, command):
    return os.path.join(project_directory, "builds/last_runs/{}.{}.{}.{}.last_run".format(environment, provider, component, command))

def get_exit_code_path(environment, provider, component, command, build_number):
    return os.path.abspath(os.path.join(project_directory, "builds/exits/{}.{}.{}.{}.{}.exitcode".format(environment, provider, component, command, build_number)))

def get_pretty_build_number(build_number):
    return "{:0>4d}".format(build_number)


def render_pipeline(run_groups):
  group_count = 1
  for index, group in enumerate(run_groups):
      print("{}/{} Group".format(index + 1, len(run_groups)))
      for item in group:
          print("{}".format(item))
      print("")
      step_outputs = retrieve_outputs(environment, item)
      print(step_outputs)

def get_builds_filename(environment, provider, component, command):
    return os.path.join(project_directory, "builds/history/{}.{}.{}.{}.json".format(environment, provider, component, command))

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

def write_builds_file(builds_filename, builds_data):
    f = open(builds_filename, 'w')
    f.write(json.dumps(builds_data, sort_keys=True, indent=4))
    f.close()

def get_outputs_filename(environment, provider, component, command):
    return os.path.join(project_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command))

class Component():
    def __init__(self, reference, environment, provider, component, command):
        self.environment = environment
        self.provider = provider
        self.component = component
        self.command = command
        self.reference = reference

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
            decoded = json.loads(open(outputs_filename).read())
        except:
            return
        pretty_build_number = "{:0>4d}".format(build_number)
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
        # builds/outputs/{}.{}.{}.{}.outputs.json
        output_filename = os.path.abspath(os.path.join(project_directory, "outputs/{}.{}.{}.{}.json".format(environment, provider, component, command)))
        with open(output_filename, 'w') as output_file:
          output_file.write(json.dumps(decoded))
        run(["aws", "s3", "cp", output_filename, "s3://vvv-{}-outputs/{}/{}/{}/{}.json"
            .format(environment, provider, component, command, pretty_build_number)])

        # env.update(json.loads(outputs))
        # pprint(env)

        print("{} {} Build passed".format(dependency, pretty_build_number))
        # run(["git", "tag", "-d", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)
        run(["git", "tag", "pipeline/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)

        last_run_path = get_last_run_path(environment, provider, component, command)
        open(os.path.join(last_run_path), 'w').write(':)')

    def calculate_state(self):
        builds, last_build_status, next_build = get_builds(self.environment, self.provider, self.component, self.command)
        for build in builds:
            build_number = build["build_number"]
            exit_code_path = get_exit_code_path(self.environment, self.provider, self.component, self.command, build_number)

            if "pid" in build and not os.path.isfile(exit_code_path) and build.get('status') == "running":
                if not psutil.pid_exists(build["pid"]):
                    build["status"] = "failure"

            if os.path.isfile(exit_code_path) and build.get('status') == "running":
                build["status"] = "finished"
                exit_code_data = open(exit_code_path).read()
                exit_code = int(exit_code_data)
                if exit_code == 0:
                    build["success"] = True
                    outputs_filename = get_outputs_filename(self.environment, self.provider, self.component, self.command)
                    if os.path.isfile(outputs_filename):
                        self.handle_success(build)
                    else:
                        build["success"] = False
                        build["status"] = "unknown"
                else:
                    build["success"] = False
            if "pid" not in build and build["status"] == "running":
                build["status"] = "unknown"



        builds_filename = get_builds_filename(self.environment, self.provider, self.component, self.command)
        write_builds_file(builds_filename, {"builds": builds})


def main():

    parser = ArgumentParser(description="devops-pipeline")
    parser.add_argument("environment")
    parser.add_argument("--file", default="architecture.dot")
    parser.add_argument("--workers", nargs="+", default=[] )
    parser.add_argument("--keys", nargs="+", default=[] )
    parser.add_argument("--gui", action="store_true" )
    parser.add_argument("--force", action="store_true" )
    parser.add_argument("--only", nargs='+', default=[])
    parser.add_argument("--ignore", nargs='+', default=[])
    parser.add_argument("--rebuild", nargs='+', default=[])
    parser.add_argument("--manual", nargs='+', default=[])
    parser.add_argument("--no-trigger", action="store_true", default=False)

    for path in ["builds/artifacts", "builds/environments", "builds/exits",
        "builds/history", "builds/last_runs", "builds/work", "builds/outputs"]:
        if not os.path.isdir(path):
            os.makedirs(path)

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
            G.add_edge(parent, "{}/{}".format(node, "validate"))
        for children in G.successors(node):
            G.add_edge("{}/{}".format(node, "publish"), children)
        dot_graph.remove_node(node)

    tree = nx.topological_sort(dot_graph)
    ordered_environments = list(nx.topological_sort(environment_graph))

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
    }],
    "filtering": ""
    }
    for environment in ordered_environments:
        for component in components:
            state["components"].append({
                "name": component,
                "status": "green",
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
      state["running"] = sorted(state["running"], key=lambda item: item["reference"])

      for component_data in state["latest"]:
          provider, component = component_data["name"].split("/")
          for command_data in component_data["commands"]:
              command = command_data["name"]
              builds, last_build_status, next_build = get_builds(args.environment, provider, component, command)

              if builds:
                  current_build = builds[-1]
                  command_data["build_number"] = current_build["build_number"]

      return Response(json.dumps(state), content_type="application/json")

    from flask import request
    @app.route('/logs', methods=["POST"])
    def retrieve_logs():
        data = request.get_json()
        component_reference = data["component"]["name"]
        provider, component = component_reference.split("/")
        command = data["command"]["name"]
        builds, last_build_status, next_build = get_builds(args.environment, provider, component, command)
        build = builds[-1]

        log_data = open(build["log_file"]).read()

        logs = {
            "console": log_data
        }
        print("Retrieving logs {}".format(component_reference))
        return Response(json.dumps(logs), content_type="application/json")


    @app.route('/trigger', methods=["POST"])
    def trigger():
      data = request.get_json()
      print("Triggering {}".format(data["name"]))
      environment = data["environment"]
      begin_pipeline(environment, run_groups, data["name"])
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



    def run_build(work_dir, build_number,
        environment,
        dependency,
        provider,
        component,
        command,
        previous_outputs,
        builds):



        provider, component, command, manual = parse_reference(dependency)
        log_filename = "logs/{:03d}-{}-{}-{}-{}.log".format(build_number, environment, provider, component, command)
        log_file = open(os.path.join(project_directory, log_filename), 'w')
        env = {
            "OUTPUT_PATH": os.path.abspath(os.path.join(project_directory, "builds/outputs/{}.{}.{}.{}.outputs.json".format(environment, provider, component, command))),
            "EXIT_CODE_PATH": get_exit_code_path(environment, provider, component, command, build_number)
        }
        env.update(previous_outputs)
        env["BUILD_NUMBER"] = str(build_number)
        env["ENVIRONMENT"] = str(environment)
        pretty_build_number = get_pretty_build_number(build_number)

        builds_filename = get_builds_filename(environment, provider, component, command)
        ensure_file(builds_filename)
        build_data = json.loads(open(builds_filename).read())
        this_build = {
            "success": False,
            "build_number": build_number,
            "reference": dependency,
            "status": "running"
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
        build_data["builds"].append(this_build)
        write_builds_file(builds_filename, build_data)
    # tag pending before build
    # run(["git", "tag", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component,
    #    pretty_build_number)], stdout=PIPE)


        class CommandRunner(Thread):
            def run(self):
              self.error = False
              exit_code_path = get_exit_code_path(environment, provider, component, command, build_number)
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
                print("Not implemented")
                this_build["success"] = True
                open("outputs/{}-{}-{}.json".format(provider, component, command), 'w').write("{}")
                write_builds_file(builds_filename, build_data)
                remove_from_running(dependency)
                open(os.path.join(get_last_run_path(environment, provider, component, command)), 'w').write(':)')
                return

              #if args.rebuild and dependency not in args.rebuild:
            #      print("Skipping due to rebuild")
            #      return
              environment_filename = os.path.join(project_directory, "builds/environments/{}-{}-{}-{}.env".format(environment, provider, component, command))
              environment_file = open(environment_filename, 'w')
              environment_file.write(json.dumps(env, indent=4))

              runner = Popen([command,
                 environment,
                 component], cwd=os.path.join(work_dir, provider), stdin=sys.stdin, stdout=log_file, stderr=log_file,
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

                write_builds_file(builds_filename, build_data)
                remove_from_running(dependency)
                return

              Component(dependency, environment, provider, component, command).calculate_state()


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
              # print("No successful build for {}".format(parent))
              continue

          pretty_build_number = "{:0>4d}".format(last_successful_build["build_number"])
          output_filename = "outputs/{}.{}.{}.{}.json".format(environment, parent_provider, parent_component, parent_command)
          if not os.path.isfile(output_filename):
              run(["aws", "s3", "cp", "s3://vvv-{}-outputs/{}/{}/{}/{}.json".format(environment, parent_provider, parent_component, parent_command, pretty_build_number),
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

                         if manual:
                            for rebuild_item in args.rebuild:
                                if item.startswith(rebuild_item):
                                    print("Skipping manual build {}".format(item))
                                    remove_from_running(item)
                                    continue

                         component_paths_script = os.path.join(provider, "component-paths")
                         if not args.force and last_successful and os.path.isfile(component_paths_script):
                            component_paths_output = run(["component-paths", environment, component],
                                cwd=provider, stdout=PIPE).stdout.decode('utf-8').strip()
                            component_paths = component_paths_output.split("\n")

                            last_run_path = get_last_run_path(environment, provider, component, command)

                            if os.path.isfile(last_run_path):
                                find_command = ["find"] + component_paths + ["(", "-path", "*.state", "-o", "-path", "*.terraform", ")", "-prune", "-o", "-newer", os.path.abspath(last_run_path), "-print"]
                                print(" ".join(find_command))
                                changed_files = run(find_command,
                                    cwd=provider,
                                    stdout=PIPE).stdout.decode('utf-8').split("\n")
                                changed_files.pop()
                                print(changed_files)
                                if global_commands.index(command) != 0 and len(changed_files) == 0:
                                    print("Component {}/{} is up-to-date".format(component, command))
                                    continue

                         previous_outputs = retrieve_outputs(environment, item)
                         if not previous_outputs:
                             previous_outputs = {}


                         pipeline_position = global_commands.index(command)
                         if pipeline_position == 0:
                             artifacts_path = os.path.abspath("builds/artifacts")
                             destination = "{}.{}.{}.{}.tgz".format(environment, provider, component, next_build)
                             # package for a build
                             source = provider
                             package = Popen(["tar", "cvzf", "{}".format(os.path.join(artifacts_path, destination)),
                                source], stdout=open('tarout', 'w'))
                             package.communicate()
                             work_dir = project_directory
                         else:
                             # unpack last artifacts
                             parent_command = "package"
                             parent_builds, last_build_status, _ = get_builds(environment, provider, component, parent_command)
                             last_successful_build = find_last_successful_build(parent_builds)

                             if not last_successful_build:
                                continue
                             artifacts_path = os.path.abspath("builds/artifacts")
                             last_successful_build_number = last_successful_build["build_number"]
                             last_artifact_name = "{}.{}.{}.{}.tgz".format(environment, provider, component, last_successful_build_number)
                             source_artifact = os.path.abspath(os.path.join("builds/artifacts", last_artifact_name))

                             work_dir_name = "{}_{}_{}_{}_{}".format(environment, provider, component, command, next_build)
                             work_dir_path = os.path.abspath(os.path.join("builds/work", work_dir_name))
                             if not os.path.isdir(work_dir_path):
                                 os.mkdir(work_dir_path)
                             os.chdir(work_dir_path)
                             unpack = Popen(["tar", "xvf", "{}".format(os.path.join(source_artifact)),
                             "-C", work_dir_path], stdout=open('tarout', 'w'))
                             unpack.communicate()
                             work_dir = work_dir_path


                         handle = run_build(work_dir,
                           next_build,
                           environment,
                           item,
                           provider,
                           component,
                           command,
                           previous_outputs,
                           builds)
                         os.chdir(project_directory)

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
    print("Scheduling components into run groups...")
    run_groups = scheduler.parallelise_components(loaded_components)
    print("Scheduling finished... Loading...")
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
      for item in ordering:
          provider, component, command, manual = parse_reference(item)
          Component(item, args.environment, provider, component, command).calculate_state()


      for node in ordering:
          provider, component, command, manual = parse_reference(node)
          builds, last_success, next_build = get_builds(args.environment, provider, component, command)
          for build in builds:
              if build["status"] == "running":
                  state["running"].append(build)


    if args.gui:
        app.run()
    else:
        for environment in ordered_environments:
            begin_pipeline(environment, run_groups, "")






if __name__ == '__main__':
  main()
