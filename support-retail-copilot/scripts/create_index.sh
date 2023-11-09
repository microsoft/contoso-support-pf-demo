#!/bin/bash

# Get the current directory name
current_dir=${PWD##*/}

# Check if the current directory is not 'support-retail-copilot'
if [ "$current_dir" != "support-retail-copilot" ]; then
    echo "You are not in the 'support-retail-copilot' directory."
    echo "Please change to that folder and run this script with 'sh scripts/exp.sh'"
    exit 1
fi

python search/init_search.py