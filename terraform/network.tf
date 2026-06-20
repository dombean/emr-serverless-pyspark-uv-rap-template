# ---------------------------------------------------------------------------
# Networking for EMR Studio.
#
# EMR Studio requires a VPC with subnets. This file provisions a minimal one
# -- a public subnet for the NAT gateway and two private subnets for the
# Studio workspaces -- created only when var.enable_emr_studio = true.
#
# The NAT gateway is the main running cost (~$0.05/hour plus data); leave
# enable_emr_studio off (the default) when not using the Studio.
#
# Spark Connect (the recommended way to develop interactively) does NOT use
# any of this -- it connects over a public gRPC/TLS endpoint with no VPC.
# ---------------------------------------------------------------------------

locals {
  network_count = var.enable_emr_studio ? 1 : 0
  network_name  = "${var.app_name}-${var.deploy_env}"

  # AWS-recommended tag referenced by the EMR Studio service role policy.
  emr_managed_tag = { "for-use-with-amazon-emr-managed-policies" = "true" }
}

data "aws_availability_zones" "available" {
  count = local.network_count
  state = "available"
}

resource "aws_vpc" "main" {
  count                = local.network_count
  cidr_block           = var.studio_vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.network_name}-vpc"
    Environment = var.deploy_env
  })
}

resource "aws_internet_gateway" "main" {
  count  = local.network_count
  vpc_id = aws_vpc.main[0].id

  tags = {
    Name        = "${local.network_name}-igw"
    Environment = var.deploy_env
  }
}

# Public subnet hosts the NAT gateway.
resource "aws_subnet" "public" {
  count                   = local.network_count
  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = cidrsubnet(var.studio_vpc_cidr, 8, 0)
  availability_zone       = data.aws_availability_zones.available[0].names[0]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${local.network_name}-public"
    Environment = var.deploy_env
  }
}

# Private subnets host the Studio workspaces.
resource "aws_subnet" "private" {
  count             = local.network_count == 1 ? 2 : 0
  vpc_id            = aws_vpc.main[0].id
  cidr_block        = cidrsubnet(var.studio_vpc_cidr, 8, count.index + 1)
  availability_zone = data.aws_availability_zones.available[0].names[count.index]

  tags = merge(local.emr_managed_tag, {
    Name        = "${local.network_name}-private-${count.index}"
    Environment = var.deploy_env
  })
}

resource "aws_eip" "nat" {
  count  = local.network_count
  domain = "vpc"

  tags = {
    Name        = "${local.network_name}-nat-eip"
    Environment = var.deploy_env
  }
}

resource "aws_nat_gateway" "main" {
  count         = local.network_count
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name        = "${local.network_name}-nat"
    Environment = var.deploy_env
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  count  = local.network_count
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }

  tags = {
    Name        = "${local.network_name}-public-rt"
    Environment = var.deploy_env
  }
}

resource "aws_route_table" "private" {
  count  = local.network_count
  vpc_id = aws_vpc.main[0].id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[0].id
  }

  tags = {
    Name        = "${local.network_name}-private-rt"
    Environment = var.deploy_env
  }
}

resource "aws_route_table_association" "public" {
  count          = local.network_count
  subnet_id      = aws_subnet.public[0].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_route_table_association" "private" {
  count          = local.network_count == 1 ? 2 : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

# Keeps S3 traffic (workspace storage) off the NAT gateway.
resource "aws_vpc_endpoint" "s3" {
  count             = local.network_count
  vpc_id            = aws_vpc.main[0].id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private[0].id]

  tags = {
    Name        = "${local.network_name}-s3-endpoint"
    Environment = var.deploy_env
  }
}
