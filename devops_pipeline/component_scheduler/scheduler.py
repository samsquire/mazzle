import collections
from ortools.sat.python import cp_model
from pprint import pprint


def parallelise_components(component_data):
    """Schedule components for maximum paralellism"""
    model = cp_model.CpModel()

    component_vars = {}
    task_run = collections.namedtuple('task_run', 'start group')
    horizon = len(component_data)
    lookup = {}
    for component in component_data:
        lookup[component["name"]] = component
        suffix = component["name"]
        start_var = model.NewIntVar(0, horizon, 'start/' + suffix)
        group_var = model.NewIntVar(0, 100, 'group/' + suffix)
        component_vars[suffix] = task_run(start_var, group_var)

    def recurse_ancestors(component, this_var):
        for ancestor in lookup[component]["ancestors"]:
            model.Add(component_vars[ancestor].start < this_var.start)
            recurse_ancestors(ancestor, this_var)
    parallel_group = collections.defaultdict(list)
    successor_lookup = {}
    ancestor_lookup = {}
    for component in component_data:
        this_var = component_vars[component["name"]]
        # recurse_ancestors(component["name"], this_var)
        for ancestor in component["ancestors"]:
            model.Add(component_vars[ancestor].start < this_var.start)
            # model.Add(component_vars[ancestor].group == this_var.group)
        for successor in component["successors"]:

            model.Add(component_vars[successor].start > this_var.start)
        successor_lookup[component["name"]] = component["successors"]
        ancestor_lookup[component["name"]] = component["ancestors"]



    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    orderings = collections.defaultdict(list)
    positions = {}
    roots = []
    threads = []
    thread_list = []
    if not (status == cp_model.FEASIBLE or status == cp_model.OPTIMAL):
        return


    for component in component_data:
        position = solver.Value(component_vars[component["name"]].start)
        positions[component["name"]] = position
        print("{} is at {}".format(component["name"], position))
        orderings[position].append(component["name"])



    afters = collections.defaultdict(list)
    last_forks = []
    for ordering in sorted(orderings):
        forks = []
        for index, fork in enumerate(orderings[ordering]):
            forks.append(fork)
            for parent in last_forks:
                if parent in ancestor_lookup[fork]:
                    afters[parent].append(fork)
        last_forks = forks


    for ordering in orderings:
        threads.append(orderings[ordering])

    def dict_to_list(things):
        items = []
        for key in sorted(things):
            items.append(things[key])
        return items


    return threads

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
