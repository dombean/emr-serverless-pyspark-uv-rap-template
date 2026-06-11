variable "aws_region" {
  description = "The AWS region to deploy the resources to."
  type        = string
  default     = "eu-west-2"
}

variable "app_name" {
  description = "A name for your application, used to prefix resource names."
  type        = string
  default     = "emr-spark-uv"
}

variable "deploy_env" {
  description = "The deployment environment (e.g., dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "s3_artifact_bucket_name" {
  description = "The name of the S3 bucket for storing job artifacts and logs."
  type        = string
  default     = "your-artifacts-bucket"
}

variable "ecr_repository_name" {
  description = "The name of the ECR repository for your Docker images."
  type        = string
  default     = "emr-pyspark"
}

variable "iceberg_s3_bucket_name" {
  description = "The name of the dedicated S3 bucket for the Iceberg data warehouse."
  type        = string
  default     = "your-iceberg-data-bucket"
}

variable "iceberg_glue_db_name" {
  description = "The name of the AWS Glue Database for the Iceberg catalogue."
  type        = string
  default     = "emr_serverless_iceberg"
}

variable "enable_remote_debugging" {
  description = "Create the VPC, NAT gateway, and SSM bastion used for remote debugging of EMR Serverless jobs. Costs money while enabled -- turn off when not debugging."
  type        = bool
  default     = false
}

variable "debug_vpc_cidr" {
  description = "CIDR block for the remote-debugging VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "debug_port" {
  description = "TCP port the Spark driver uses to reach the debugger through the bastion."
  type        = number
  default     = 3535
}

variable "bastion_ssh_public_key" {
  description = "SSH public key granted access to the bastion as ec2-user (used for the reverse tunnel). Leave empty to add a key manually via SSM instead."
  type        = string
  default     = ""
}

variable "bastion_instance_type" {
  description = "Instance type for the debug bastion."
  type        = string
  default     = "t3.micro"
}

variable "enable_emr_studio" {
  description = "Create an EMR Studio (IAM auth mode) for interactive notebook development against EMR Serverless. Shares the VPC and NAT gateway with the remote-debugging stack."
  type        = bool
  default     = false
}
