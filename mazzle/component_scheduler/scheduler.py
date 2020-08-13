from threading import Thread
import collections
from ortools.sat.python import cp_model
from pprint import pprint
import json

def parallelise_components(component_data):
    """Schedule components for maximum paralellism"""
    model = cp_model.CpModel()

    component_vars = {}
    task_run = collections.namedtuple('task_run', 'start')
    horizon = len(component_data)

    for component in component_data:
        suffix = component["name"]
        start_var = model.NewIntVar(0, horizon, 'start/' + suffix)
        component_vars[suffix] = task_run(start_var)

    parallel_group = collections.defaultdict(list)
    successor_lookup = {}
    for component in component_data:
        this_var = component_vars[component["name"]]

        for ancestor in component["ancestors"]:
            model.Add(component_vars[ancestor].start < this_var.start)
        for successor in component["successors"]:
            model.Add(component_vars[successor].start > this_var.start)
        successor_lookup[component["name"]] = component["successors"]

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    orderings = collections.defaultdict(list)
    positions = {}
    roots = []
    threads = []
    thread_list = []
    if status == cp_model.FEASIBLE or status == cp_model.OPTIMAL:
        for component in component_data:
            position = solver.Value(component_vars[component["name"]].start)
            positions[component["name"]] = position
            component["position"] = position
            orderings[position].append(component["name"])

        highest = max(positions.values())
        items = list(orderings.keys())
        results = []

        pprint(results)

    return list(sorted(component_data, key=lambda item: item["position"])), orderings

#parallelisable_builds = parallelise_components(component_data=json.loads(open("../backup-infra/builds/loaded.json").read()))
#pprint(parallelisable_builds)
#parallelisable_builds = parallelise_components(component_data = [
#
#      {
#          "name": "terraform/vpc/plan",
#          "ancestors": ["terraform/vpc/validate"],
#          "successors": ["terraform/vpc/run"]
#      },
#      {
#          "name": "terraform/vpc/run",
#          "ancestors": ["terraform/vpc/plan"],
#          "successors": ["terraform/vpc/test", "terraform/vpc/deploy"]
#      },
#      {
#          "name": "terraform/vpc/deploy",
#          "ancestors": ["terraform/vpc/run"],
#          "successors": []
#      },
#      {
#          "name": "terraform/vpc/test",
#          "ancestors": ["terraform/vpc/run"],
#          "successors": ["integration"]
#      },
#
#      {
#          "name": "terraform/users/validate",
#          "ancestors": [],
#          "successors": ["terraform/users/plan"]
#      },
#      {
#          "name": "terraform/users/plan",
#          "ancestors": ["terraform/users/validate"],
#          "successors": ["terraform/users/run"]
#      },
#      {
#          "name": "terraform/users/run",
#          "ancestors": ["terraform/users/plan"],
#          "successors": ["terraform/users/test"]
#      },
#      {
#          "name": "terraform/users/test",
#          "ancestors": ["terraform/users/run"],
#          "successors": ["integration"]
#      },
#      {
#          "name": "terraform/vpc/validate",
#          "ancestors": [],
#          "successors": ["terraform/vpc/plan"]
#      },
#      {   "name": "integration",
#        "ancestors": ["terraform/vpc/test", "terraform/users/test"],
#        "successors": ["terraform/services/validate"]
#      },
#      {
#        "name": "terraform/services/validate",
#        "ancestors": ["integration"],
#        "successors": []
#      },
#
#
#      {
#          "name": "terraform/bastion/plan",
#          "ancestors": ["terraform/bastion/validate"],
#          "successors": ["terraform/bastion/run"]
#      },
#      {
#          "name": "terraform/bastion/run",
#          "ancestors": ["terraform/bastion/plan"],
#          "successors": ["terraform/bastion/test"]
#      },
#      {
#          "name": "terraform/bastion/deploy",
#          "ancestors": ["terraform/bastion/run"],
#          "successors": []
#      },
#      {
#          "name": "terraform/bastion/test",
#          "ancestors": ["terraform/bastion/run"],
#          "successors": []
#      },
#      {
#          "name": "terraform/bastion/validate",
#          "ancestors": [],
#          "successors": ["terraform/bastion/plan"]
#      },
#
#
#
# ])
#pprint(parallelisable_builds)
