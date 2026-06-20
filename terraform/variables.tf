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

variable "enable_emr_studio" {
  description = "Create an EMR Studio (IAM auth mode) for interactive notebook development against EMR Serverless, together with the VPC and NAT gateway it requires. Costs money while enabled -- leave off unless you specifically want the Studio (Spark Connect needs none of this)."
  type        = bool
  default     = false
}

variable "studio_vpc_cidr" {
  description = "CIDR block for the EMR Studio VPC."
  type        = string
  default     = "10.42.0.0/16"
}
