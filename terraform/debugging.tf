# ---------------------------------------------------------------------------
# Remote debugging infrastructure for EMR Serverless.
#
# Implements the reverse-SSH-tunnel pattern from
# https://github.com/aws-samples/remote-debugging-with-emr in Terraform:
#
#   laptop (IDE debug server :3535)
#     --ssh-over-SSM--> bastion (reverse tunnel binds :3535)
#     <--outbound TCP-- Spark driver (EMR Serverless worker in private subnet)
#
# The VPC, subnets, NAT gateway, and EMR worker security group are shared
# with EMR Studio (studio.tf), so they are created when either
# var.enable_remote_debugging or var.enable_emr_studio is true. The bastion
# and its IAM role/key are debugging-only. The NAT gateway and bastion cost
# money while they exist, so leave the flags off (the default) when not in use.
# ---------------------------------------------------------------------------

locals {
  vpc_count   = var.enable_remote_debugging || var.enable_emr_studio ? 1 : 0
  debug_count = var.enable_remote_debugging ? 1 : 0
  debug_name  = "${var.app_name}-debug-${var.deploy_env}"

  # AWS-recommended tag referenced by the EMR Studio service role policy.
  emr_managed_tag = { "for-use-with-amazon-emr-managed-policies" = "true" }
}

data "aws_availability_zones" "available" {
  count = local.vpc_count
  state = "available"
}

# --- Network -----------------------------------------------------------------

resource "aws_vpc" "debug" {
  count                = local.vpc_count
  cidr_block           = var.debug_vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.debug_name}-vpc"
    Environment = var.deploy_env
  })
}

resource "aws_internet_gateway" "debug" {
  count  = local.vpc_count
  vpc_id = aws_vpc.debug[0].id

  tags = {
    Name        = "${local.debug_name}-igw"
    Environment = var.deploy_env
  }
}

# Public subnet hosts the bastion and the NAT gateway.
resource "aws_subnet" "debug_public" {
  count                   = local.vpc_count
  vpc_id                  = aws_vpc.debug[0].id
  cidr_block              = cidrsubnet(var.debug_vpc_cidr, 8, 0)
  availability_zone       = data.aws_availability_zones.available[0].names[0]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${local.debug_name}-public"
    Environment = var.deploy_env
  }
}

# Private subnets host the EMR Serverless worker ENIs and Studio workspaces.
resource "aws_subnet" "debug_private" {
  count             = local.vpc_count == 1 ? 2 : 0
  vpc_id            = aws_vpc.debug[0].id
  cidr_block        = cidrsubnet(var.debug_vpc_cidr, 8, count.index + 1)
  availability_zone = data.aws_availability_zones.available[0].names[count.index]

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.debug_name}-private-${count.index}"
    Environment = var.deploy_env
  })
}

resource "aws_eip" "debug_nat" {
  count  = local.vpc_count
  domain = "vpc"

  tags = {
    Name        = "${local.debug_name}-nat-eip"
    Environment = var.deploy_env
  }
}

resource "aws_nat_gateway" "debug" {
  count         = local.vpc_count
  allocation_id = aws_eip.debug_nat[0].id
  subnet_id     = aws_subnet.debug_public[0].id

  tags = {
    Name        = "${local.debug_name}-nat"
    Environment = var.deploy_env
  }

  depends_on = [aws_internet_gateway.debug]
}

resource "aws_route_table" "debug_public" {
  count  = local.vpc_count
  vpc_id = aws_vpc.debug[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.debug[0].id
  }

  tags = {
    Name        = "${local.debug_name}-public-rt"
    Environment = var.deploy_env
  }
}

resource "aws_route_table" "debug_private" {
  count  = local.vpc_count
  vpc_id = aws_vpc.debug[0].id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.debug[0].id
  }

  tags = {
    Name        = "${local.debug_name}-private-rt"
    Environment = var.deploy_env
  }
}

resource "aws_route_table_association" "debug_public" {
  count          = local.vpc_count
  subnet_id      = aws_subnet.debug_public[0].id
  route_table_id = aws_route_table.debug_public[0].id
}

resource "aws_route_table_association" "debug_private" {
  count          = local.vpc_count == 1 ? 2 : 0
  subnet_id      = aws_subnet.debug_private[count.index].id
  route_table_id = aws_route_table.debug_private[0].id
}

# Keeps S3 traffic (code zip, logs, Iceberg data) off the NAT gateway.
resource "aws_vpc_endpoint" "debug_s3" {
  count             = local.vpc_count
  vpc_id            = aws_vpc.debug[0].id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.debug_private[0].id]

  tags = {
    Name        = "${local.debug_name}-s3-endpoint"
    Environment = var.deploy_env
  }
}

# --- Security groups ----------------------------------------------------------

resource "aws_security_group" "emr_debug_workers" {
  count       = local.vpc_count
  name        = "${local.debug_name}-emr-workers"
  description = "EMR Serverless workers (debug VPC). Outbound only."
  vpc_id      = aws_vpc.debug[0].id

  egress {
    description = "All outbound (S3 endpoint, NAT, bastion)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.debug_name}-emr-workers"
    Environment = var.deploy_env
  }
}

resource "aws_security_group" "debug_bastion" {
  count       = local.debug_count
  name        = "${local.debug_name}-bastion"
  description = "Debug bastion. No SSH ingress; access is via SSM only."
  vpc_id      = aws_vpc.debug[0].id

  ingress {
    description     = "Debugger connections from EMR Serverless workers"
    from_port       = var.debug_port
    to_port         = var.debug_port
    protocol        = "tcp"
    security_groups = [aws_security_group.emr_debug_workers[0].id]
  }

  egress {
    description = "All outbound (SSM agent needs HTTPS)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.debug_name}-bastion"
    Environment = var.deploy_env
  }
}

# --- Bastion ------------------------------------------------------------------

data "aws_ssm_parameter" "al2023_ami" {
  count = local.debug_count
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_iam_role" "debug_bastion" {
  count = local.debug_count
  name  = "${local.debug_name}-bastion-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect    = "Allow",
        Principal = { Service = "ec2.amazonaws.com" },
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${local.debug_name}-bastion-role"
    Environment = var.deploy_env
  }
}

resource "aws_iam_role_policy_attachment" "debug_bastion_ssm" {
  count      = local.debug_count
  role       = aws_iam_role.debug_bastion[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "debug_bastion" {
  count = local.debug_count
  name  = "${local.debug_name}-bastion-profile"
  role  = aws_iam_role.debug_bastion[0].name
}

resource "aws_key_pair" "debug_bastion" {
  count      = var.enable_remote_debugging && var.bastion_ssh_public_key != "" ? 1 : 0
  key_name   = "${local.debug_name}-bastion-key"
  public_key = var.bastion_ssh_public_key

  tags = {
    Name        = "${local.debug_name}-bastion-key"
    Environment = var.deploy_env
  }
}

resource "aws_instance" "debug_bastion" {
  count                  = local.debug_count
  ami                    = data.aws_ssm_parameter.al2023_ami[0].value
  instance_type          = var.bastion_instance_type
  subnet_id              = aws_subnet.debug_public[0].id
  vpc_security_group_ids = [aws_security_group.debug_bastion[0].id]
  iam_instance_profile   = aws_iam_instance_profile.debug_bastion[0].name
  key_name               = try(aws_key_pair.debug_bastion[0].key_name, null)

  # GatewayPorts lets the reverse tunnel (-R) bind on all interfaces so the
  # Spark driver can reach it on the bastion's private IP, not just loopback.
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    cat > /etc/ssh/sshd_config.d/99-remote-debugging.conf <<'SSHD'
    GatewayPorts yes
    ClientAliveInterval 30
    ClientAliveCountMax 10
    SSHD
    systemctl restart sshd
  EOF

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    encrypted = true
  }

  tags = {
    Name        = "${local.debug_name}-bastion"
    Environment = var.deploy_env
  }
}
