# introducing devops-pipeline

## pipelines as code

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

devops-pipeline is a tool to coordinate complicated environments that are built and changed by multiple tools. An example is the combination of AWS, Terraform, Packer, shell scripts, Ansible, docker, Chef. devops-pipeline lets you chain together tools locally, on your development workstation. devops-pipeline models the flow of data between tools and uses environment variables to pass data about. devops-pipeline is meant to be used regularly while you are building complex environments.

The tools you use to bring up or change an environment are ran and configured in a certain ordering. In devops-pipeline, the ordering and dependencies between tools are explicitly configured in a **graph file**. devops-pipeline uses Graphviz dot file syntax for its configuration.

devops-pipeline is kind of a task runner and it is modelled to appear like a continuous integration server.

![pipeline-running](parallel-components.png)

devops-pipeline is meant to be simple.



By specifying what comes before what, devops-pipeline can ensure it runs your tools in the correct order.

# why devops-pipeline

* Environments are complicated
* Knowledge of how to make changes is not machine readable
* You want to make a change across the whole stack
