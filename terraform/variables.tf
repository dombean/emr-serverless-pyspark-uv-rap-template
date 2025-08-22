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
