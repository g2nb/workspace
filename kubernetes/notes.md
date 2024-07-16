# Requirements

On your laptop install the following command line utilities:

* awscli - Amazon web services client
* kubectl - Kubernetes control utility
* eksctl - Amazon EKS control utility
* helm - Kubernetes deployment tool

# Create the cluster

Run the command below. Optionally, replace `notebook-workspace` with a different 
cluster name or `us-west-2` with a different region code.

> eksctl create cluster --name notebook-workspace --region us-west-2

Let it run a few minutes to get everything set up. Once it's ready, you can check 
and see that a stack was created in CloudFormation.

https://us-west-2.console.aws.amazon.com/cloudformation/home?region=us-west-2

You can also check and see the status of all nodes in the cluster by running:

> kubectl get nodes -o wide

# Provision persistent storage

To use an EFS drive with your cluster, you first need to create an IAM role which 
the cluster wil use to access the drive. But even before you can do that, you need 
to associate the cluster with an IAM OIDC provider.

To set the IAM OIDC provider associated with cluster, run the following:

> eksctl utils associate-iam-oidc-provider --region=us-west-2 --cluster=notebook-workspace --approve

Then, to create the IAM role, run the command below, setting the `cluster_name` 
variable to the name of your cluster and optionally setting a different role name.

> export cluster_name=notebook-workspace
> export role_name=AmazonEKS_EFS_CSI_DriverRole
> eksctl create iamserviceaccount --name efs-csi-controller-sa  --namespace kube-system --cluster $cluster_name --role-name $role_name --region us-west-2 --role-only --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy --approve
> TRUST_POLICY=$(aws iam get-role --role-name $role_name --query 'Role.AssumeRolePolicyDocument' | sed -e 's/efs-csi-controller-sa/efs-csi-*/' -e 's/StringEquals/StringLike/')
> aws iam update-assume-role-policy --role-name $role_name --policy-document "$TRUST_POLICY"

Next, you need to attach the EFS driver to the cluster.

> export ROLE_ARN=$(aws iam get-role --role-name $role_name --query 'Role.[RoleName, Arn]' --output text | awk '{print $2}')
> eksctl create addon --cluster notebook-workspace --name aws-efs-csi-driver --version latest --service-account-role-arn $ROLE_ARN --region us-west-2

Finally, you'll need to create the actual EFS file system for use by the cluster, 
as well as its associated security group.

> vpc_id=$(aws eks describe-cluster --name notebook-workspace --region us-west-2 --query "cluster.resourcesVpcConfig.vpcId" --output text)
> cidr_range=$(aws ec2 describe-vpcs --vpc-ids $vpc_id --query "Vpcs[].CidrBlock" --output text --region us-west-2)
> security_group_id=$(aws ec2 create-security-group --group-name EFS-EKS-Security-Group --description "Access EFS drive from EKS" --vpc-id $vpc_id --region us-west-2 --output text)
> aws ec2 authorize-security-group-ingress --group-id $security_group_id --protocol tcp --port 2049 --cidr $cidr_range --region us-west-2
> file_system_id=$(aws efs create-file-system --region us-west-2 --performance-mode generalPurpose --query 'FileSystemId' --output text)
> aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc_id" --query 'Subnets[*].{SubnetId: SubnetId,AvailabilityZone: AvailabilityZone,CidrBlock: CidrBlock}' --region us-west-2 --output table | awk '{print $6}' | xargs -Ixxx aws efs create-mount-target --file-system-id $file_system_id --security-groups $security_group_id --region us-west-2 --subnet-id xxx

> kubectl --namespace=g2nb-workspace apply -f test_efs.yaml
> kubectl --namespace=g2nb-workspace apply -f test_efs_claim.yaml

# Setting up JupyterHub

We will use helm charts to automate as much as JupyterHub's setup as possible. 
First, however, you must make your helm installation aware of JupyterHub's chart
repository by running the following:

> helm repo add jupyterhub https://hub.jupyter.org/helm-chart/
> helm repo update

Next, install the chart using the provided `config.yaml` file (located in the same 
directory as these notes). Feel free to customize the `namespace` name provided.

> helm upgrade --cleanup-on-fail --install g2nb-workspace jupyterhub/jupyterhub --namespace g2nb-workspace --create-namespace --version=3.3.7 --values config.yaml

You can make sure all the necessary pods are created by running the following:

> kubectl get pod --namespace g2nb-workspace

# Tearing down the cluster

Run the following command.

> eksctl delete cluster --name notebook-workspace --region us-west-2