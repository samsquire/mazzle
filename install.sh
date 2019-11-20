#!/usr/bin/env bash

install_dir=$(pwd)

echo """
export PATH=\${PATH}:${install_dir}/devops_pipeline
""" | sudo tee /etc/profile.d/devops-pipeline.sh


