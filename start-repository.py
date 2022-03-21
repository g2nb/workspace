#!/usr/bin/env python3

import os
import sys
import argparse
import subprocess

##########################################
# Get the user's home directory          #
##########################################

home_dir = os.path.expanduser('~')
aws_dir = os.path.join(home_dir, '.aws')

##########################################
# Get the arguments passed to the script #
##########################################

# Handle the --data and --port options
parser = argparse.ArgumentParser(description='Start the Docker container for the Notebook Repository')
parser.add_argument('-d', '--data', type=str, default='/data', help='Set the data directory to be mounted in the container')
parser.add_argument('-p', '--port', type=int, default=80, help='Set the port the repository will be available at')
parser.add_argument('-n', '--network', type=str, default='repo', help='The name of the Docker network to run on')
parser.add_argument('-a', '--aws', type=str, default=aws_dir, help='The location of the your AWS credentials (~/.aws)')
parser.add_argument('-t', '--theme', type=str, default='', help='Path to theme to be mounted into the container')
parser.add_argument('-c', '--container', type=str, default='workspace', help='Name given to the container')

# Parse the arguments
args = parser.parse_args()

##########################################
# Set up the network, if necessary       #
##########################################

network_summary = subprocess.run(f'docker network inspect {args.network}'.split(), stdout=subprocess.PIPE).stdout.decode('utf-8')
network_exists = False if network_summary == '[]\n' else True
if not network_exists:
    subprocess.run(f'docker network create --driver overlay --attachable {args.network}'.split())

##########################################
# Set up the data directory, if needed   #
##########################################

# Check if /data exists and create lazily if needed
if not os.path.exists(args.data):
    os.mkdir(args.data)
if not os.path.isdir(args.data):
    sys.exit(f'{args.data} is not a directory')

# Check if subdirectories exist and create lazily if needed
required_subdirs = ['repository', 'users', 'shared', 'defaults']
for subdir in required_subdirs:
    subdir_path = os.path.join(args.data, subdir)
    if not os.path.exists(subdir_path):
        os.mkdir(subdir_path)
    if not os.path.isdir(subdir_path):
        sys.exit(f'{subdir_path} is not a directory')

# Check if necessary files exist
db_exists = os.path.exists(os.path.join(args.data, 'jupyterhub.sqlite'))
config_exists = os.path.exists(os.path.join(args.data, 'jupyterhub_config.py'))
projects_exists = os.path.exists(os.path.join(args.data, 'projects_config.py'))

# Start temp container and copy files, if necessary
if not db_exists or not config_exists or not projects_exists:
    print('Starting temporary container')
    subprocess.Popen('docker run --name=copy_data genepattern/notebook-repository'.split())
    subprocess.run('sleep 10'.split())

# Get the database, if necessary
if not db_exists:
    print('Copying database')
    subprocess.run(f'docker cp copy_data:/data/jupyterhub.sqlite {args.data}/jupyterhub.sqlite'.split())

# Get the config file, if necessary
if not config_exists:
    print('Copying configuration')
    subprocess.run(f'docker cp copy_data:/data/jupyterhub_config.py {args.data}/jupyterhub_config.py'.split())

# Get the settings file, if necessary
if not projects_exists:
    print('Copying settings')
    subprocess.run(f'docker cp copy_data:/data/projects_config.py {args.data}/projects_config.py'.split())

# Clean up the temporary container
if not db_exists or not config_exists or not projects_exists:
    print('Shutting down temporary container')
    subprocess.run('docker stop copy_data'.split())
    subprocess.run('docker rm copy_data'.split())

##########################################
# Create the theme mount points          #
##########################################

if args.theme and os.path.exists(args.theme) and os.path.isdir(args.theme):
    theme_mounts = ''

    # Import images
    image_dir = os.path.join(args.theme, "images")
    if os.path.exists(image_dir) and os.path.isdir(image_dir):
        for f in os.listdir(image_dir):
            if f.endswith('.jpg') or f.endswith('.png') or f.endswith('.gif') or f.endswith('.jpeg'):
                theme_mounts += f' -v {args.theme}/images/{f}:/opt/conda/share/jupyterhub/static/images/{f}'

    # Import css
    css_dir = os.path.join(args.theme, "css")
    if os.path.exists(css_dir) and os.path.isdir(css_dir):
        for f in os.listdir(css_dir):
            if f.endswith('.css'):
                theme_mounts += f' -v {args.theme}/css/{f}:/opt/conda/share/jupyterhub/static/css/{f}'

    # Import fonts
    font_dir = os.path.join(args.theme, "fonts")
    if os.path.exists(font_dir) and os.path.isdir(font_dir):
        for f in os.listdir(font_dir):
            if f.endswith('.eot') or f.endswith('.woff') or f.endswith('.ttf') or f.endswith('.svg'):
                theme_mounts += f' -v {args.theme}/fonts/{f}:/opt/conda/share/jupyterhub/static/fonts/{f}'

    # Import templates
    template_dir = os.path.join(args.theme, "templates")
    if os.path.exists(template_dir) and os.path.isdir(template_dir):
        for f in os.listdir(template_dir):
            if f.endswith('.html'):
                theme_mounts += f' -v {args.theme}/templates/{f}:/opt/conda/share/jupyterhub/templates/{f}'
else:
    theme_mounts = ''

##########################################
# Start the Notebook Repository          #
##########################################

try:
    subprocess.Popen(f'docker run --rm \
                                  --net={args.network} \
                                  --name={args.container} \
                                  -e DATA_DIR={args.data} \
                                  -p {args.port}:80 \
                                  -v {args.data}:/data \
                                  -v {args.aws}:/root/.aws \
                                  {theme_mounts} \
                                  -v /var/run/docker.sock:/var/run/docker.sock g2nb/workspace'.split())
except KeyboardInterrupt:
    print('Shutting down Notebook Repository')
