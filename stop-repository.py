#!/usr/bin/env python3

import subprocess
import argparse


##########################################
# Get the arguments passed to the script #
##########################################

# Handle the --data and --port options
parser = argparse.ArgumentParser(description='Stop the Docker container for the Notebook Repository')
parser.add_argument('-c', '--container', type=str, default='workspace', help='Name given to the container')

# Parse the arguments
args = parser.parse_args()

##########################################
# Stop the container                     #
##########################################

try:
    subprocess.Popen(f'docker stop {args.container}'.split())
except KeyboardInterrupt:
    print('Shutting down Notebook Repository')
