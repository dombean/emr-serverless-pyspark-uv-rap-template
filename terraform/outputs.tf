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
