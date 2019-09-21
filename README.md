# devops-pipeline

**Prototype code** This is a prototype and the code is not refactored. YMMV

[ui screenshot](docs/parallel-components.png)

This tool chains together common DevOps tools into a pipeline. A single code repository contains your infrastructure code.

Model the data flow of your tools as a Graphviz graph file and this tool can orchestrate your tools to bring up your entire environment with one command. The tool will validate, apply, test and package each of your tools in the correct order.

# Modelling your infrastructure in Graphviz

Each node in your architecture graph should be named `provider/component` When devops-pipeline runs, it expands the graph into one it can actually execute. This includes the full lifecycle of a component. This is:

`validate` -> `test` -> `run` -> `package`

`terraform/webserver/run` is a reference to the `terraform` provider which is the directory of terraform code.  `webserver` is the component and `run` is a command. Commands are shell scripts in the provider directory so you can extend


## Example – an AMI pipeline

You want to use Chef to install Java and create an AWS AMI from that cookbook and then spin up an AWS instance that has Java pre-installed.

![AMIPipeline](/docs/example-01.png)

1. You have a Chef cookbook called ‘ubuntu-java’ that can install Java
2. You have a packer template file called ‘ubuntu-java.json’.
3. You have a terraform folder called ‘ubuntu-java’.

The word after the tool name is the component name.

# Example - Managing the lifecycle of volumes, AMIs and system packages


Resources such as volumes, system packages and AMIs change infrequently and remain for an extended period. We can mark these resources as manually triggered resources with a '*' symbol. While your infrastructure changes rapidly around them, these are updated less frequently. Devops-pipeline will try avoid doing work it does not need to do.

# Example - Prometheus and Vault cluster

See [fun-infra repo](https://github.com/samsquire/fun-infra)

![FunInfra](/docs/example-02.png)

* Sets up a Prometheus instance for monitoring instances.
* Installs node_exporter on Vault, NAT instance and bastion.
* Sets up a Certificate authority on a Hashicorp Vault server instance.
* Initializes the Vault automatically and encrypts the secrets.
* Creates an AMI with the certificate authority certificate pre-installed.

# Supported tools

* Chef
* Packer
* Terraform
* Local shell

# Usage

The tool will try avoid doing work that it doesn't need to do. It accomplishes this via Git tagging.

To re-build everything in an environment, we run:
```
devops-pipeline environment
```


## Full arguments

```
devops-pipeline environment \
  --file architecture.dot \
  –-show \
  --key "Key comment or email" \
  –-gui \
  --no-trigger \
  --force \
  –-rebuild [component] \
  --ignore [component]
  ```

`--file` overrides what file to run

`--show` does not apply any changes and just shows what the tool would have done.

`--no-trigger` prevents components from triggering other components.

`--force` stops detection of changes and rebuilds every component.

`--keys` a list of GPG key names or email addresses to encrypt secrets with

`--ignore` if you don't want to rebuild a particular component, you can stop it running entirely

`--gui` a rudimentary build monitor
