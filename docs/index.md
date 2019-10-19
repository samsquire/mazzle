# introducing devops-pipeline

devops-pipeline is a tool to coordinate complicated environments that are built from multiple tools.

## pipelines as code

Write self-descriptive pipelines in dot syntax that are renderable by graphviz and executable by this tool.

![](java-server.svg)

```
digraph G {
   rankdir="LR";
   "packer/ubuntu" -> "terraform/appserver";
}
```

![](gradle-app.svg)

```
digraph G {
  rankdir="LR";
  "ansible/machines" -> "gradle/app" -> "ansible/deploy" -> "ansible/release";
}
```

# introduction

`devops-pipeline` is for deterministically creating computer environments. An example environment is one that uses AWS, Terraform, Packer, shell scripts, Ansible, docker, Chef. `devops-pipeline` allows you to chain together tools for running on your developer workstation. devops-pipeline models the flow of data between tools and uses environment variables to pass along data. devops-pipeline is meant to be used after each change whereby it runs validations, unit tests, smoke tests and deployments tests.

# parallel execution

`devops-pipeline` knows what parts of your environment infrastructure can run together in paralell (concurrently and in parallel) due to the graphs defining 

![pipeline-running](parallel-components.png)

The tools you use to bring up or change an environment are ran and configured in a certain ordering. In devops-pipeline, the ordering and dependencies between tools are explicitly configured in a **graph file**. devops-pipeline uses Graphviz dot file syntax for its configuration.

devops-pipeline is kind of a task runner and it is modelled to appear like a continuous integration server.



devops-pipeline is meant to be simple.



By specifying what comes before what, devops-pipeline can ensure it runs your tools in the correct order.

# why devops-pipeline

* Environments are complicated
* Knowledge of how bring up a new environment is not machine readable
* You want to make a change to a complicated system that will affect every thing, you need a repeatable way to test.
