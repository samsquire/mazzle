# introducing devops-pipeline

This is a prototype. YMMV

devops-pipeline is a command line tool to coordinate large complicated environments that are built from multiple devops tools. devops-pipeline is kind of a task runner and its web GUI is modelled to appear like a continuous integration server.

## infrastructure as code and pipelines as code

Write self-descriptive pipelines in dot syntax renderable by graphviz and executable by this tool. devops-pipeline uses [Graphviz dot file syntax](https://en.wikipedia.org/wiki/DOT_(graph_description_language)) for its configuration. In devops-pipeline, you **specify the order of pipeline execution and flow of data between components**.


# parallel build execution

`devops-pipeline` knows what parts of your environment infrastructure can run together concurrently and in parallel due to its configuration being a graph file. Here is an example graph and GUI screenshot.

[![architecture](architecture.svg)](https://github.com/samsquire/devops-pipeline/blob/master/docs/architecture.svg)

![pipeline-running](parallel-components.png)

Notice how dns, security, vault volume can all begin running at the same time.

## features

 * **Simple GUI** You can use the GUI to trigger builds
 * **Fast builds** devops-pipeline only runs parts of your pipeline that need to run by detecting if they have been changed since the last run.
 * **Parallelisation of devops tools** devops-pipeline knows what part of your infrastructure can run simultaneously, in parallel.

### Example - building and using an AMI

![](java-server.svg)

file: architecture.dot
```
digraph G {
   rankdir="LR";
   "packer/ubuntu" -> "terraform/appserver";
}
```

In the above pipeline `packer/ubuntu` is a `component` that that uses packer to create machine images on AWS with Java installed. **packer/ubuntu outputs an AMI ID.** `terraform/appserver` is another component that needs this AMI ID to bring up a new instance running that AMI.

## Example - building and releasing a Java app

![](gradle-app.svg)

file: architecture.dot

```
digraph G {
  rankdir="LR";
  "ansible/machines" -> "gradle/app" -> "ansible/deploy" -> "ansible/release";
}
```
`ansible/machines` is a component that provisions machines running java.
`gradle/app` is a component that builds from source a Java app. One of `gradle/app`'s outputs is a path to an artifact; a set of jar files.

# introduction

`devops-pipeline` is for deterministically creating computer environments. An example environment is one that could use AWS, Terraform, Packer, shell scripts, Ansible, docker, Chef. `devops-pipeline` allows you to chain together tools for running on your developer workstation. devops-pipeline models the flow of data between tools and uses environment variables to pass along data. devops-pipeline is meant to be used after each change whereby it runs validations, unit tests, smoke tests and deployments tests.

# quickstart

TODO

# how it works and adding new tools to devops-pipeline

To understand how devops-pipeline works, you need to understand the directory structure. **Your code is separated by directory by each tool**. Like a **monorepository**, you divide your code by tool, so you have a directory for ansible code, a directory for terraform code. Devops-pipeline walks your pipeline and runs shellscripts inside each directory to activate each tool.

For example:

```
ansible/
shellscript/
terraform/
packer/
chef/
```

# Lifecycle Commands

Devops-pipeline runs lifecycle commands inside provider directories. It runs a lifecycle commands within the provider directory. Some lifecycle commands will be familiar, such as:

 * **validate**
 * **test**
 * **run**

Supporting additional tools in devops-pipeline is simple. You need to provide at the very least, a `run` script for that tool. You place this inside the provider directory. So, to introducea new devops tool **xyz**, you would create an **xyz** directory and introduce a **run** script in the **xyz** directory **xyz/run**.

## run

Run needs to handle following environment variables:

* EXIT_CODE_PATH
* OUTPUT_PATH

## Internal lifecycle command: component-paths

devops-pipeline uses the `component-paths` script to detect if a component has changed. This script should return all files linked to the component.

```
./ansible/component-paths <environment> <component>
```

The above command should return all the files for running component

# SSH workers

You don't always want to run builds on the master node (where you run devops-pipeline from) You can specify a list of hosts to run builds on remote servers **via SSH**.

```
devops-pipeline --file architecture.dot \
    --gui \
    --workers node1 node2 \
    --workers-key ~/.ssh/worker-ssh-key \
    --workers-user ubuntu
```

## idiom - provision SSH workers at the beginning of your pipeline

Unlike Jenkins and gocd, worker nodes are considered to be part of your pipeline. An idiom in `devops-pipeline` is that your early stages in your pipeline is provisioning worker nodes. These worker nodes run the remainder of the build. You can replace `--workers` with `--discover-workers-from-output <output name>` where `output name` is the name of an ouput from your machine provisioning component that contains a list of server hostnames or IP addresses that you can SSH onto.

Here is an example of ansible provisioning EC2 instances and installing dependencies on worker nodes, then running packer to build an AMI and launching that AMI with terraform.

![](worker-provisioning.svg)

The at symbol `@` at the beginning of a component reference means that this component builds on the master node.

```
digraph G {
	rankdir="LR";
	"@ansible/machines" -> "@ansible/provision-workers"-> "packer/source-ami" -> "terraform/appservers";
}
```

## idiom - building development workstations

An idiom is that developer workstations are provisioned by **devops-pipeline** which are your workstations you use for development.

![](devbox.svg)

```
digraph G {
	"@vagrant/devbox" -> "@ansible/workers" -> "@ansible/workers-provision";
}
```

# Quickstart


# why devops-pipeline

* Environments are complicated
* Knowledge of how bring up a new environment is not machine readable
* You want to make a change to a complicated system that will affect every thing, you need a repeatable way to test.
