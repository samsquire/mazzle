#!/usr/bin/env python3
from threading import Thread
import collections

from functools import partial
from flask import Flask, render_template, Response
app = Flask(__name__)

import os
cwd = os.getcwd()
print(cwd)

from argparse import ArgumentParser
from networkx.drawing.nx_pydot import read_dot, write_dot
from networkx.readwrite import json_graph
import networkx as nx
import sys, json
from sys import stdout
from pprint import pprint
from subprocess import Popen, PIPE, run, call


def parse_reference(reference):
  provider, component_name, command = reference.split("/")
  component = component_name.replace("*","")
  return provider, component, command, "*" in component_name


def main():

  parser = ArgumentParser(description="devops-pipeline")
  parser.add_argument("environment")
  parser.add_argument("--file", default="architecture.dot")
  parser.add_argument("--show", action="store_true" )
  parser.add_argument("--keys", nargs="+", default=[] )
  parser.add_argument("--gui", action="store_true" )
  parser.add_argument("--force", action="store_true" )
  parser.add_argument("--only", nargs='+', default=[])
  parser.add_argument("--ignore", nargs='+', default=[] )
  parser.add_argument("--rebuild", nargs='+', default=[])
  parser.add_argument("--manual", nargs='+', default=[])
  parser.add_argument("--no-trigger", action="store_true", default=False)

  args = parser.parse_args()

  dot_graph = read_dot(args.file)
  environment_graph = read_dot("environments.dot")
  G = dot_graph

  for node in list(dot_graph.nodes()):
    steps = ["validate", "plan", "run", "test", "publish"]
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
  # queued devops tool runs, each list item is a separate parallel job
  # [[], [], []]


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

      return render_template('build.html', jobs=[])

  @app.route('/json')
  def return_json():
      jobs = []
      print(ordering)
      for environment in ordered_environments:
        jobs = jobs + list(map(partial(create_jobs, environment), ordering))

      return json.dumps(jobs)


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
    return "pipeline/{}/{}/{}/*".format(args.environment, provider, component)

  def pending_build_info(environment, provider, component):
    return "pipeline/pending/{}/{}/{}/*".format(args.environment, provider, component)

  def sorted_nicely( l ):
      """ Sort the given iterable in the way that humans expect."""
      convert = lambda text: int(text) if text.isdigit() else text
      alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key) ]
      return sorted(l, key = alphanum_key)

  def get_builds(environment, provider, component):
    query = build_info(environment, provider, component)
    builds = run(["git", "tag", "-l", query], stdout=PIPE)
    tags = builds.stdout.decode('utf-8').split("\n")
    tags.pop()
    tags = sorted_nicely(tags)

    pending_build_query = pending_build_info(environment, provider, component)
    run_pending_build = run(["git", "tag", "-l", pending_build_query], stdout=PIPE)
    pending_tags = run_pending_build.stdout.decode('utf-8').split("\n")
    pending_tags.pop()
    pending_builds = sorted_nicely(pending_tags)

    if len(tags) == 0:
      next_build = 1
    else:
      next_build = int(tags[-1].split("/")[-1]) + 1

    last_build_status = True
    if pending_builds:
      last_failing_build = int(pending_builds[-1].split("/")[-1])
      # print("{}/{} Next build would be {} last failing build was {}".format(provider, component, next_build, last_failing_build))
      if next_build <= last_failing_build:
        last_build_status = False
        next_build = int(last_failing_build) + 1

    return (tags, last_build_status, next_build)

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

  def run_build(parent, build_number, count, environment, dependency, provider, component, command, previous_outputs):
    provider, component, command, manual = parse_reference(dependency)

    log_file = open("logs/{:03d}-{}-{}-{}-{}.log".format(count, args.environment, provider, component, command), 'w+')
    env = {}
    env.update(previous_outputs)
    env["BUILD_NUMBER"] = str(build_number)
    env["ENVIRONMENT"] = str(environment)
    pretty_build_number = "{:0>4d}".format(build_number)
    # tag pending before build
    run(["git", "tag", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component,
        pretty_build_number)], stdout=PIPE)


    class CommandRunner(Thread):
        def run(self):
          if parent:
            print("Waiting for parent")
            parent.join()
            print("Parent finished")
          if not os.path.isfile(os.path.join(provider, command)):
            print("Skipping {}".format(command))
            return
          pprint(env)
          if args.rebuild and dependency not in args.rebuild:
              return
          runner = Popen([command,
             environment,
             component], cwd=provider, stdout=log_file, stderr=log_file,
             env=env)

          print("{}".format(log_file.name))
          runner.communicate(input=None, timeout=None)
          runner.wait(timeout=None)

          # outputs = result.decode('utf-8')

          decoded = json.loads(open("{}/build/{}.outputs.json".format(provider, component)).read())

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
          output_filename = "outputs/{}-{}-{}.json".format(provider, component, pretty_build_number)
          with open(output_filename, 'w') as output_file:
            output_file.write(json.dumps(decoded))
          run(["aws", "s3", "cp", output_filename, "s3://vvv-{}-outputs/{}/{}/{}.json".format(environment, provider, component, pretty_build_number)])

          # env.update(json.loads(outputs))
          # pprint(env)

          if runner.returncode == 0:
            print("{} Build passed".format(pretty_build_number))
            run(["git", "tag", "-d", "pipeline/pending/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)
            run(["git", "tag", "pipeline/{}/{}/{}/{}".format(environment, provider, component, pretty_build_number)], stdout=PIPE)
            return runner, True
          else:
            print("{} Build failed {}".format(pretty_build_number, runner.returncode))
            raise BuildFailure()


    worker_thread = CommandRunner()
    worker_thread.start()
    return worker_thread



  def retrieve_outputs(node):
    provider, component, command, manual = parse_reference(node)
    parents = list(ancestors(G, node))
    env = {}
    for parent in parents:
      parent_provider, parent_component, parent_command, manual = parse_reference(parent)
      parent_builds, last_build_status, next_build = get_builds(args.environment, parent_provider, parent_component)
      if not parent_builds or parent_command != "run":
        continue
      last_successful_build = int(parent_builds[-1].split("/")[-1])
      pretty_build_number = "{:0>4d}".format(last_successful_build)
      output_filename = "outputs/{}-{}-{}.json".format(parent_provider, parent_component, pretty_build_number)
      if not os.path.isfile(output_filename):
          run(["aws", "s3", "cp", "s3://vvv-{}-outputs/{}/{}/{}.json".format(args.environment, parent_provider, parent_component, pretty_build_number),
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
    tags, last_build_status, next_build = get_builds(environment, provider, component)

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
  if args.gui:
     app.run()

  worker_threads = []

  if not args.show:
    finished_builds = {}
    parent = None
    for count, node in enumerate(ordering):
      provider, component, command, manual = parse_reference(node)
      if args.rebuild and node not in args.rebuild:
          continue
      if manual and node not in args.manual:
          continue

      if node in finished_builds:
          print("Skipping already scheduled build")
          continue
      builds, last_build_status, next_build = get_builds(args.environment, provider, component)
      print("")
      # print("Running {} {}...".format(node, next_build))
      previous_outputs = retrieve_outputs(node)
      print("Waiting for {}".format(node))
      parent = run_build(None, next_build,
        count + 1,
        args.environment,
        node,
        provider,
        component,
        command,
        previous_outputs)
      worker_threads.append(parent)

      finished_builds[node] = True

      for child in G.successors(node):
          if child in finished_builds:
              continue
          provider, component, command, manual = parse_reference(child)
          builds, last_build_status, next_build = get_builds(args.environment, provider, component)
          previous_outputs = retrieve_outputs(child)
          if manual and node not in args.manual:
              continue
          child_worker = run_build(parent, next_build, count + 1,
            args.environment, child, provider, component, command,
            previous_outputs)
          worker_threads.append(child_worker)
          finished_builds[child] = True
    print("Waiting for workers to finish")
    for thread in worker_threads:
      thread.join()



if __name__ == '__main__':
  main()
