#!/usr/bin/env bash

install_dir=$(pwd)

echo """
export MAZZLE_HOME=${install_dir}/mazzle
export PATH=\${PATH}:${install_dir}/mazzle
""" | sudo tee /etc/profile.d/mazzle.sh

