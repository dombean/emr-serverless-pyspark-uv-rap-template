output "S3_BUCKET" {
  description = "The name of the S3 bucket created for EMR artifacts."
  value       = aws_s3_bucket.emr_artifacts.bucket
}

output "IMAGE_URI" {
  description = "The URL of the ECR repository created for the EMR application."
  value       = aws_ecr_repository.emr_app.repository_url
}

output "EMR_EXECUTION_ROLE" {
  description = "The ARN of the IAM role created for EMR Serverless execution."
  value       = aws_iam_role.emr_serverless_execution_role.arn
}

output "ICEBERG_S3_BUCKET" {
  description = "The name of the S3 bucket created for the Iceberg data warehouse."
  value       = aws_s3_bucket.iceberg_data.bucket
}

output "ICEBERG_GLUE_DB" {
  description = "The name of the AWS Glue Database created for Iceberg."
  value       = aws_glue_catalog_database.iceberg_db.name
}

output "DEBUG_BASTION_INSTANCE_ID" {
  description = "Instance ID of the debug bastion (SSH target via SSM)."
  value       = try(aws_instance.debug_bastion[0].id, null)
}

output "DEBUG_HOST" {
  description = "Private IP of the debug bastion -- the address the Spark driver connects to."
  value       = try(aws_instance.debug_bastion[0].private_ip, null)
}

output "DEBUG_SUBNET_IDS" {
  description = "Comma-separated private subnet IDs for the EMR Serverless application's network configuration."
  value       = var.enable_remote_debugging ? join(",", aws_subnet.debug_private[*].id) : null
}

output "DEBUG_EMR_SECURITY_GROUP_ID" {
  description = "Security group ID for EMR Serverless workers in the debug VPC."
  value       = try(aws_security_group.emr_debug_workers[0].id, null)
}

output "EMR_STUDIO_ID" {
  description = "ID of the EMR Studio."
  value       = try(aws_emr_studio.this[0].id, null)
}

output "EMR_STUDIO_URL" {
  description = "URL for opening the EMR Studio in a browser."
  value       = try(aws_emr_studio.this[0].url, null)
}
