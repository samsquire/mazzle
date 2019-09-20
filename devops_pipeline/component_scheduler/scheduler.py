import collections
from ortools.sat.python import cp_model
from pprint import pprint

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


    for component in component_data:
        this_var = component_vars[component["name"]]
        model.Minimize(this_var.start)
        for ancestor in component["ancestors"]:
            model.Add(component_vars[ancestor].start < this_var.start)
        for successor in component["successors"]:
            model.Add(component_vars[successor].start > this_var.start)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    parallel_ordering = collections.defaultdict(list)
    parallel_list = []
    if status == cp_model.FEASIBLE or status == cp_model.OPTIMAL:
        for component, var in component_vars.items():
            current_batch = parallel_ordering[solver.Value(var.start)]
            current_batch.append(component)

    for key in sorted(parallel_ordering):
        parallel_list.append(parallel_ordering[key])
    return parallel_list

#parallelisable_builds = parallelise_components(component_data = [
#      {
#          "name": "terraform/vpc/validate",
#          "ancestors": [],
#          "successors": ["terraform/vpc/plan"]
#      },
#      {
#          "name": "terraform/users/validate",
#          "ancestors": [],
#          "successors": []
#      },
#      {
#          "name": "terraform/users/test",
#          "ancestors": ["terraform/users/validate"],
#          "successors": []
#      },
#      {
#          "name": "terraform/vpc/plan",
#          "ancestors": ["terraform/vpc/validate"],
#          "successors": ["terraform/vpc/test"]
#      },
#      {
#          "name": "terraform/vpc/run",
#          "ancestors": ["terraform/vpc/test"],
#          "successors": []
#      },
#      {
#          "name": "terraform/vpc/test",
#          "ancestors": ["terraform/vpc/validate"],
#          "successors": ["terraform/vpc/run"]
#      }
#
# ])
#pprint(parallelisable_builds)
