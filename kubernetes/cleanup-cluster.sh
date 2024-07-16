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
# Tear down the cluster                                    #
############################################################

# Get the name of the attached EFS drive
efs_id=$(kubectl get --output jsonpath='{.parameters.fileSystemId}' storageclass efs-sc)

# Clean up all services, pods and any remaining PVCs
kubectl delete --namespace $namespace services --all
kubectl delete pod --namespace $namespace --all
kubectl delete --namespace $namespace pvc --all

# Delete the namespace
eksctl delete cluster --name $cluster_name --region $aws_region --force

# Delete the EKS-EFS security group
aws ec2 delete-security-group --group-name $security_group $aws_region

# Delete the attached EFS drive
aws efs describe-mount-targets --file-system-id $efs_id --region $aws_region --output text | awk '{print $7}' | xargs -Imount_id aws efs delete-mount-target --mount-target-id mount_id --region $aws_region
aws efs delete-file-system --file-system-id $efs_id --region $aws_region
