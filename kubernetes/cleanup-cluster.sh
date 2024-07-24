#!/bin/bash

############################################################
# Help                                                     #
############################################################
Help() {
   echo "Tears down a kubernetes cluster for a notebook workspace"
   echo
   echo "Syntax: setup-cluster.sh [-n|r|v|V]"
   echo "options:"
   echo "n     Cluster name"
   echo "r     AWS Region"
   echo "s     EFS-EKS security group name"
   echo "j     JupyterHub service namespace"
   echo "h     Print help message"
   echo ""
}

############################################################
# Global variables                                         #
############################################################

cluster_name="notebook-workspace"
aws_region="us-west-2"
security_group="EFS-EKS-Security-Group"
namespace="g2nb-workspace"

############################################################
# Process the input options.                               #
############################################################

while getopts ":hn:r:s:j:" option; do
   case "${option}" in
      h) # Display Help
         Help
         exit;;
      n) cluster_name=${OPTARG};;   # Cluster name
      r) aws_region=${OPTARG};;     # AWS region
      s) security_group=${OPTARG};; # EFS security group name
      j) namespace=${OPTARG};;      # JupyterHub service namespace
     \?) # Invalid option
         echo "Error: Invalid option"
         exit;;
   esac
done

############################################################
# Shut down the JupyterLab application                     #
############################################################

helm uninstall --namespace $namespace $namespace
sleep 10

############################################################
# Tear down the cluster                                    #
############################################################

# Get the name of the attached EFS drive and VPC
efs_id=$(kubectl get --output jsonpath='{.parameters.fileSystemId}' storageclass efs-sc)
vpc_id=$(eksctl get cluster --region $aws_region $cluster_name | tail -1 | awk '{print $5}')

# Clean up all services, pods, pvc and namespaces
kubectl delete --namespace $namespace services --all
kubectl delete pod --namespace $namespace --all
kubectl delete --namespace $namespace pvc --all
kubectl delete namespace $namespace
kubectl delete storageclass efs-sc

# Delete the cluster
sleep 10
eksctl delete cluster --name $cluster_name --region $aws_region

# Delete the attached EFS drive
sleep 10
aws efs describe-mount-targets --file-system-id $efs_id --region $aws_region --output text | awk '{print $7}' | xargs -Imount_id aws efs delete-mount-target --mount-target-id mount_id --region $aws_region
sleep 20
aws efs delete-file-system --file-system-id $efs_id --region $aws_region
sleep 10

# Delete the EKS-EFS security group
group_id=$(aws ec2 describe-security-groups --filter Name=vpc-id,Values=$vpc_id Name=group-name,Values=$security_group --query 'SecurityGroups[*].[GroupId]' --output text --region $aws_region)
aws ec2 delete-security-group --group-id $group_id --region $aws_region

# Delete the VPC
# NO LONGER NECESSARY?
# This last step still needs to be done manually. To do it automatically we must first perfect deleting all components of the VPC:

#Delete your security group by using the delete-security-group command.
#
#aws ec2 delete-security-group --group-id sg-id
#
#Delete each network ACL by using the delete-network-acl command.
#
#aws ec2 delete-network-acl --network-acl-id acl-id
#
#Delete each subnet by using the delete-subnet command.
#
#aws ec2 delete-subnet --subnet-id subnet-id
#
#Delete each custom route table by using the delete-route-table command.
#
#aws ec2 delete-route-table --route-table-id rtb-id
#
#Detach your internet gateway from your VPC by using the detach-internet-gateway command.
#
#aws ec2 detach-internet-gateway --internet-gateway-id igw-id --vpc-id vpc-id
#
#Delete your internet gateway by using the delete-internet-gateway command.
#
#aws ec2 delete-internet-gateway --internet-gateway-id igw-id
#
#[Dual stack VPC] Delete your egress-only internet gateway by using the delete-egress-only-internet-gateway command.
#
#aws ec2 delete-egress-only-internet-gateway --egress-only-internet-gateway-id eigw-id
#
#Delete your VPC by using the delete-vpc command.
#
#aws ec2 delete-vpc --vpc-id vpc-id
# aws ec2 describe-vpcs --region $aws_region --filters Name=tag:alpha.eksctl.io/cluster-name,Values=$cluster_name