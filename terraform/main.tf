provider "aws" {
  region = var.aws_region
}

# Bucket for EMR job artifacts and logs
resource "aws_s3_bucket" "emr_artifacts" {
  bucket        = "${var.s3_artifact_bucket_name}-${var.deploy_env}"
  force_destroy = true

  tags = {
    Name        = "${var.app_name}-artifacts-${var.deploy_env}"
    Environment = var.deploy_env
  }
}

# Dedicated bucket for Iceberg data warehouse
resource "aws_s3_bucket" "iceberg_data" {
  bucket        = "${var.iceberg_s3_bucket_name}-${var.deploy_env}"
  force_destroy = true

  tags = {
    Name        = "${var.app_name}-iceberg-data-${var.deploy_env}"
    Environment = var.deploy_env
  }
}

resource "aws_ecr_repository" "emr_app" {
  name         = var.ecr_repository_name
  force_delete = true

  tags = {
    Name        = "${var.app_name}-ecr-repo"
    Environment = var.deploy_env
  }
}

# AWS Glue Database for Iceberg
resource "aws_glue_catalog_database" "iceberg_db" {
  name = "${var.iceberg_glue_db_name}_${var.deploy_env}"
}

data "aws_iam_policy_document" "emr_serverless_execution_policy" {
  statement {
    sid    = "FullAccessToArtifactBucket"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:DeleteObject",
    ]
    resources = [
      aws_s3_bucket.emr_artifacts.arn,
      "${aws_s3_bucket.emr_artifacts.arn}/*",
    ]
  }

  statement {
    sid    = "FullAccessToIcebergBucket"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:DeleteObject",
    ]
    resources = [
      aws_s3_bucket.iceberg_data.arn,
      "${aws_s3_bucket.iceberg_data.arn}/*",
    ]
  }

  statement {
    sid    = "GlueCreateAndReadDataCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:CreateDatabase",
      "glue:GetDataBases",
      "glue:CreateTable",
      "glue:GetTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:CreatePartition",
      "glue:BatchCreatePartition",
      "glue:GetUserDefinedFunctions",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchDescribe"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchCreateAndWrite"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/emr-serverless*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/emr-serverless*:*",
    ]
  }
}

resource "aws_iam_role" "emr_serverless_execution_role" {
  name = "${var.app_name}-emr-execution-role-${var.deploy_env}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "emr-serverless.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.app_name}-emr-execution-role"
    Environment = var.deploy_env
  }
}

resource "aws_iam_role_policy" "emr_serverless_execution_policy" {
  name   = "${var.app_name}-emr-execution-policy-${var.deploy_env}"
  role   = aws_iam_role.emr_serverless_execution_role.id
  policy = data.aws_iam_policy_document.emr_serverless_execution_policy.json
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ecr_repo_policy" {
  statement {
    sid    = "EmrServerlessCustomImageSupport"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }

    actions = [
      "ecr:BatchGetImage",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
    ]

    condition {
      test     = "StringLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:emr-serverless:${var.aws_region}:${data.aws_caller_identity.current.account_id}:/applications/*"]
    }
  }
}

resource "aws_ecr_repository_policy" "emr_app" {
  repository = aws_ecr_repository.emr_app.name
  policy     = data.aws_iam_policy_document.ecr_repo_policy.json
}
