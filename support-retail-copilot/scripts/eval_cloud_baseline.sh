#!/bin/bash

# Get the current directory name
current_dir=${PWD##*/}

# Check if the current directory is not 'support-retail-copilot'
if [ "$current_dir" != "support-retail-copilot" ]; then
    echo "You are not in the 'support-retail-copilot' directory."
    echo "Please change to that folder and run this script with 'sh scripts/exp.sh'"
    exit 1
fi

# create a name for the run if no command line parameter was given
if [ -z "$1" ]; then
    run_name=run_$(date +%Y%m%d_%H%M%S)
else
    run_name=$1
fi

run_name_eval="${run_name}_eval"
echo "run name: $run_name"
echo "eval name: $run_name_eval"
# create the run
pfazure run create -f scripts/yaml/baseline_job.yaml --name $run_name --stream
# evaluate the run
pfazure run create -f scripts/yaml/eval_job.yaml --run $run_name --stream --name $run_name_eval