#!/bin/bash

############################################################
# Help                                                     #
############################################################
Help() {
   echo "Set up a kubernetes cluster for a notebook workspace using EKS and ESF"
   echo
   echo "Syntax: setup-cluster.sh [-n|r|d|s|j|h]"
   echo "options:"
   echo "n     Cluster name"
   echo "r     AWS Region"
   echo "d     EKS-EFS driver role name"
   echo "s     EFS-EKS security group name"
   echo "j     Namespace for the JupyterHub service"
   echo "h     Print help message"
   echo ""
}

############################################################
# Global variables                                         #
############################################################

cluster_name="notebook-workspace"
aws_region="us-west-2"
role_name="AmazonEKS_EFS_CSI_DriverRole"
security_group="EFS-EKS-Security-Group"
namespace="g2nb-workspace"

############################################################
# Process the input options.                               #
############################################################

while getopts ":hn:r:d:s:j:" option; do
   case "${option}" in
      h) # Display Help
         Help
         exit;;
      n) cluster_name=${OPTARG};;   # Cluster name
      r) aws_region=${OPTARG};;     # AWS region
      d) role_name=${OPTARG};;      # EFS driver role name
      s) security_group=${OPTARG};; # EFS security group name
      j) namespace=${OPTARG};;      # JupyterHub service namespace
     \?) # Invalid option
         echo "Error: Invalid option"
         exit;;
   esac
done

############################################################
# Create the cluster                                       #
############################################################

echo "CREATING THE CLUSTER"
eksctl create cluster --name $cluster_name --region $aws_region

############################################################
# Wait for nodes to be available                           #
############################################################

output=""
count=0

until [[ $output =~ Ready ]]; do
    echo 'Querying for cluster completion...'
    output=$(kubectl get nodes | sed '1d' | awk '{print $2}' 2>&1)
    ((count++))
    sleep 60
done

printf '\n%s\n' "Cluster creation completed successfully after $count attempts."

############################################################
# Provision persistent storage                             #
############################################################

# Set the IAM OIDC provider associated with cluster
echo "SETTING UP THE IAM OIDC PROVIDER"
eksctl utils associate-iam-oidc-provider --region=$aws_region --cluster=$cluster_name --approve

# Create the IAM role
echo "CREATING THE IAM ROLE"
eksctl create iamserviceaccount --name efs-csi-controller-sa  --namespace kube-system --cluster $cluster_name --role-name $role_name --region $aws_region --role-only --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy --approve
TRUST_POLICY=$(aws iam get-role --role-name $role_name --query 'Role.AssumeRolePolicyDocument' | sed -e 's/efs-csi-controller-sa/efs-csi-*/' -e 's/StringEquals/StringLike/')
aws iam update-assume-role-policy --role-name $role_name --policy-document "$TRUST_POLICY"

# Attach the EFS driver to the cluster
echo "ATTACHING THE EFS DRIVER TO THE CLUSTER"
ROLE_ARN=$(aws iam get-role --role-name $role_name --query 'Role.[RoleName, Arn]' --output text | awk '{print $2}')
eksctl create addon --cluster $cluster_name --name aws-efs-csi-driver --version latest --service-account-role-arn $ROLE_ARN --region $aws_region

# Create the EFS file system for use by the cluster
echo "CREATING THE EFS FILE SYSTEM"
vpc_id=$(aws eks describe-cluster --name $cluster_name --region $aws_region --query "cluster.resourcesVpcConfig.vpcId" --output text)
cidr_range=$(aws ec2 describe-vpcs --vpc-ids $vpc_id --query "Vpcs[].CidrBlock" --output text --region $aws_region)
security_group_id=$(aws ec2 create-security-group --group-name $security_group --description "Access EFS drive from EKS" --vpc-id $vpc_id --region $aws_region --output text)
aws ec2 authorize-security-group-ingress --group-id $security_group_id --protocol tcp --port 2049 --cidr $cidr_range --region $aws_region
file_system_id=$(aws efs create-file-system --region $aws_region --performance-mode generalPurpose --query 'FileSystemId' --output text)
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc_id" --query 'Subnets[*].{SubnetId: SubnetId,AvailabilityZone: AvailabilityZone,CidrBlock: CidrBlock}' --region $aws_region --output text | awk '{print $3}' | xargs -Isubnet_id aws efs create-mount-target --file-system-id $file_system_id --security-groups $security_group_id --region $aws_region --subnet-id subnet_id

# Create the EFS storage class
echo "CREATING THE EFS STORAGE CLASS"
echo "{ \"apiVersion\": \"storage.k8s.io/v1\", \"kind\": \"StorageClass\", \"metadata\": { \"name\": \"efs-sc\", \"annotations\": { \"storageclass.kubernetes.io/is-default-class\": \"true\" } }, \"provisioner\": \"efs.csi.aws.com\", \"parameters\": { \"provisioningMode\": \"efs-ap\", \"fileSystemId\": \"${file_system_id}\", \"directoryPerms\": \"700\", \"gidRangeStart\": \"1000\", \"gidRangeEnd\": \"2000\", \"basePath\": \"/dynamic_provisioning\", \"subPathPattern\": \"\${.PVC.namespace}/\${.PVC.name}\", \"ensureUniqueDirectory\": \"true\", \"reuseAccessPoint\": \"false\" }}" | kubectl apply -f -

############################################################
# Deploy JupyterHub                                        #
############################################################

# Load the JupyterHub helm chart
echo "LOADING THE JUPYTERHUB HELM CHART"
helm repo add jupyterhub https://hub.jupyter.org/helm-chart/
helm repo update

# Deploy JupyterHub to the cluster
echo "DEPLOYING THE JUPYTERHUB APPLICATION TO THE CLUSTER"
helm upgrade --cleanup-on-fail --install $namespace jupyterhub/jupyterhub --namespace $namespace --create-namespace --version=3.3.7 --values jupyterhub-config.yaml

# Return the public URL of the hub, run:
sleep 10
echo "Wait for all pods to start up and then visit the following URL... It may take a few minutes."
echo http://$(kubectl --namespace $namespace get service proxy-public --output jsonpath='{.status.loadBalancer.ingress[].hostname}')

# You can make sure all the necessary pods are created by running the following:
# > kubectl get pod --namespace $namespace

# If one is stuck in the pending stats, you can debug by running:
# > kubectl describe pod --namespace $namespace <POD-ID>

# If it's stuck because of a PVC issue, you can debug by running:
# > kubectl describe pvc --namespace $namespace hub-db-dir
