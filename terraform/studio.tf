# ---------------------------------------------------------------------------
# EMR Studio -- the web-based notebook IDE for interactive EMR Serverless
# development.
#
# Created only when var.enable_emr_studio = true. Uses the VPC, private
# subnets, and NAT gateway defined in network.tf. Uses IAM auth mode, so no
# IAM Identity Center setup is needed: anyone who can sign in to the AWS
# console with the right IAM permissions can open the Studio URL.
#
# The Studio itself is free; the shared NAT gateway is the running cost.
# ---------------------------------------------------------------------------

locals {
  studio_count = var.enable_emr_studio ? 1 : 0
  studio_name  = "${var.app_name}-studio-${var.deploy_env}"
}

# --- Security groups ----------------------------------------------------------
# Two SGs are required by EMR Studio: the workspace SG (notebook kernels/UI)
# and the engine SG (cluster attachment; required by the API even for
# serverless-only use). Rules are standalone resources because the two groups
# reference each other.

resource "aws_security_group" "studio_workspace" {
  count       = local.studio_count
  name        = "${local.studio_name}-workspace"
  description = "EMR Studio workspaces."
  vpc_id      = aws_vpc.main[0].id

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.studio_name}-workspace"
    Environment = var.deploy_env
  })
}

resource "aws_security_group" "studio_engine" {
  count       = local.studio_count
  name        = "${local.studio_name}-engine"
  description = "EMR Studio engine."
  vpc_id      = aws_vpc.main[0].id

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.studio_name}-engine"
    Environment = var.deploy_env
  })
}

resource "aws_vpc_security_group_egress_rule" "studio_workspace_to_engine" {
  count                        = local.studio_count
  security_group_id            = aws_security_group.studio_workspace[0].id
  description                  = "Workspace to engine (Livy)"
  ip_protocol                  = "tcp"
  from_port                    = 18888
  to_port                      = 18888
  referenced_security_group_id = aws_security_group.studio_engine[0].id
}

resource "aws_vpc_security_group_egress_rule" "studio_workspace_https" {
  count             = local.studio_count
  security_group_id = aws_security_group.studio_workspace[0].id
  description       = "HTTPS out (Git repositories, package installs)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "studio_engine_from_workspace" {
  count                        = local.studio_count
  security_group_id            = aws_security_group.studio_engine[0].id
  description                  = "Engine from workspace (Livy)"
  ip_protocol                  = "tcp"
  from_port                    = 18888
  to_port                      = 18888
  referenced_security_group_id = aws_security_group.studio_workspace[0].id
}

# --- Service role --------------------------------------------------------------
# Follows the policy AWS documents for EMR Studio service roles, scoped to
# resources tagged for-use-with-amazon-emr-managed-policies = true.

data "aws_iam_policy_document" "studio_assume_role" {
  count = local.studio_count

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["elasticmapreduce.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:elasticmapreduce:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
    }
  }
}

data "aws_iam_policy_document" "studio_service_policy" {
  count = local.studio_count

  statement {
    sid       = "AllowEMRReadOnlyActions"
    effect    = "Allow"
    actions   = ["elasticmapreduce:ListInstances", "elasticmapreduce:DescribeCluster", "elasticmapreduce:ListSteps"]
    resources = ["*"]
  }

  statement {
    sid       = "AllowEC2ENIActionsWithEMRTags"
    effect    = "Allow"
    actions   = ["ec2:CreateNetworkInterfacePermission", "ec2:DeleteNetworkInterface"]
    resources = ["arn:aws:ec2:*:*:network-interface/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/for-use-with-amazon-emr-managed-policies"
      values   = ["true"]
    }
  }

  statement {
    sid     = "AllowEC2ENIAttributeAction"
    effect  = "Allow"
    actions = ["ec2:ModifyNetworkInterfaceAttribute"]
    resources = [
      "arn:aws:ec2:*:*:instance/*",
      "arn:aws:ec2:*:*:network-interface/*",
      "arn:aws:ec2:*:*:security-group/*",
    ]
  }

  statement {
    sid    = "AllowEC2SecurityGroupActionsWithEMRTags"
    effect = "Allow"
    actions = [
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:DeleteNetworkInterfacePermission",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/for-use-with-amazon-emr-managed-policies"
      values   = ["true"]
    }
  }

  statement {
    sid       = "AllowEC2ENICreationWithEMRTags"
    effect    = "Allow"
    actions   = ["ec2:CreateNetworkInterface"]
    resources = ["arn:aws:ec2:*:*:network-interface/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/for-use-with-amazon-emr-managed-policies"
      values   = ["true"]
    }
  }

  statement {
    sid     = "AllowEC2ENICreationInSubnetAndSecurityGroupWithEMRTags"
    effect  = "Allow"
    actions = ["ec2:CreateNetworkInterface"]
    resources = [
      "arn:aws:ec2:*:*:subnet/*",
      "arn:aws:ec2:*:*:security-group/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/for-use-with-amazon-emr-managed-policies"
      values   = ["true"]
    }
  }

  statement {
    sid       = "AllowAddingTagsDuringEC2ENICreation"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = ["arn:aws:ec2:*:*:network-interface/*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values   = ["CreateNetworkInterface"]
    }
  }

  statement {
    sid    = "AllowEC2ReadOnlyActions"
    effect = "Allow"
    actions = [
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeTags",
      "ec2:DescribeInstances",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AllowSecretsManagerReadOnlyActionsWithEMRTags"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:*:secret:*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/for-use-with-amazon-emr-managed-policies"
      values   = ["true"]
    }
  }

  statement {
    sid    = "AllowWorkspaceStorage"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
      "s3:GetEncryptionConfiguration",
    ]
    resources = [
      aws_s3_bucket.emr_artifacts.arn,
      "${aws_s3_bucket.emr_artifacts.arn}/*",
    ]
  }
}

resource "aws_iam_role" "studio_service_role" {
  count              = local.studio_count
  name               = "${local.studio_name}-service-role"
  assume_role_policy = data.aws_iam_policy_document.studio_assume_role[0].json

  tags = {
    Name        = "${local.studio_name}-service-role"
    Environment = var.deploy_env
  }
}

resource "aws_iam_role_policy" "studio_service_policy" {
  count  = local.studio_count
  name   = "${local.studio_name}-service-policy"
  role   = aws_iam_role.studio_service_role[0].id
  policy = data.aws_iam_policy_document.studio_service_policy[0].json
}

# --- Studio --------------------------------------------------------------------

resource "aws_emr_studio" "this" {
  count                       = local.studio_count
  name                        = local.studio_name
  auth_mode                   = "IAM"
  vpc_id                      = aws_vpc.main[0].id
  subnet_ids                  = aws_subnet.private[*].id
  service_role                = aws_iam_role.studio_service_role[0].arn
  workspace_security_group_id = aws_security_group.studio_workspace[0].id
  engine_security_group_id    = aws_security_group.studio_engine[0].id
  default_s3_location         = "s3://${aws_s3_bucket.emr_artifacts.bucket}/emr-studio"
  description                 = "Interactive notebook IDE for ${var.app_name} (${var.deploy_env})."

  tags = {
    Name        = local.studio_name
    Environment = var.deploy_env
  }
}
