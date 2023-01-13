#!/usr/bin/env python

##################################################################################
# To use this script your aws credentials must be located at: ~/.aws/credentials #
# Use the awscli (aws configure) to put them there if necessary.                 #
##################################################################################

import boto3
import time
import datetime
import argparse

##########################################
# Parse the command line arguments       #
##########################################

parser = argparse.ArgumentParser(description='Create a new compute node AMI and update autoscale group')
parser.add_argument('-o', '--oldami', type=str, default='ami-0a590f0cc96076975', help='Image ID of the AMI to build off of')
parser.add_argument('-l', '--launchtemplate', type=str, default='lt-097a7a92aae1f54b4', help='ID of the launch template to modify')
parser.add_argument('-d', '--delete', type=bool, default=False, help='Delete the old AMI after the new one is built')

# Parse the arguments
args = parser.parse_args()

##########################################
# Call the EC2 commands                  #
##########################################

# Get the EC2 clients
client = boto3.client('ec2', region_name='us-east-1')
ec2 = boto3.resource('ec2', region_name='us-east-1')

# Launch the existing AMI and run the Docker image update script
print('Launching temporary instance')
resp = client.run_instances(ImageId=args.oldami, InstanceType='t2.micro',
                            MinCount=1, MaxCount=1, UserData='/data/compute/pull_container.sh')
instance_id = resp['Instances'][0]['InstanceId']
instance = ec2.Instance(id=instance_id)
print(f'Instance created: {instance_id}')

# Wait for the instance to be initialized
print('Waiting for instance to be initialized')
waiter = client.get_waiter('instance_status_ok')
waiter.wait(
    InstanceIds=[instance_id],
    Filters=[{
        "Name": "instance-status.reachability",
        "Values": [ "passed" ]
    }]
)
print('Initialization complete')

# Wait for the images to pull (TODO: Find a better way to do this)
print('Waiting for Docker images to pull')
time.sleep(60 * 20)
print('Pull complete')

# Shut down the instance
print('Shutting down the temporary instance')
client.stop_instances(InstanceIds=[instance_id])
instance.wait_until_stopped()
time.sleep(60)
print('Instance stopped')

# Create the new AMI
print('Creating the new AMI')
image = instance.create_image(Name=f'g2nb Compute ({datetime.datetime.now().strftime("%m-%d-%Y")})')
print(f'AMI created: {image.id}')

# Wait for the instance to be ready
print('Waiting for the image to complete initialization')
waiter = client.get_waiter('image_available')
waiter.wait(ImageIds=[image.id],
            Filters=[{
                "Name": "state",
                "Values": [ "available" ]
            }]
)

# Wait for the image to build (TODO: Find a better way to do this)
time.sleep(60 * 10)
print('Initialization complete')

# Clean up the instance
print('Cleaning up temporary instance')
instance.terminate()

# Update the launch template
print('Creating the new launch template version')
response = client.create_launch_template_version(
            LaunchTemplateId=args.launchtemplate,
            SourceVersion="$Latest",
            VersionDescription="Updating Docker images",
            LaunchTemplateData={ "ImageId": image.id }
        )

# Clean up the old AMI
if args.delete:
    print('Deregistering the old AMI')
    image.deregister()
    print('Deregister complete')

print('COMPLETE')