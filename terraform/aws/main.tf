provider "aws" {
  region = var.aws_region
  default_tags { tags = var.tags }
}

locals {
  azs = [
    "${var.aws_region}a",
    "${var.aws_region}b",
    "${var.aws_region}c",
  ]
}

# -----------------------------------------------------------------------------
# VPC + Subnets
# -----------------------------------------------------------------------------

resource "aws_vpc" "wake" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "${var.cluster_name}-vpc" }
}

resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.wake.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone = local.azs[count.index]
  tags = {
    Name                                = "${var.cluster_name}-private-${count.index}"
    "kubernetes.io/role/internal-elb"   = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_subnet" "public" {
  count                   = 3
  vpc_id                  = aws_vpc.wake.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index + 3)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags = {
    Name                                = "${var.cluster_name}-public-${count.index}"
    "kubernetes.io/role/elb"            = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_internet_gateway" "wake" {
  vpc_id = aws_vpc.wake.id
}

resource "aws_eip" "nat" {
  count = 3
  domain = "vpc"
}

resource "aws_nat_gateway" "wake" {
  count         = 3
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.wake.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.wake.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 3
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = 3
  vpc_id = aws_vpc.wake.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.wake[count.index].id
  }
}

resource "aws_route_table_association" "private" {
  count          = 3
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# -----------------------------------------------------------------------------
# EKS + Postgres + S3 (module-delegated)
# -----------------------------------------------------------------------------

module "eks" {
  source = "./modules/eks"

  cluster_name        = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  vpc_id              = aws_vpc.wake.id
  private_subnet_ids  = aws_subnet.private[*].id
  node_instance_type  = var.node_instance_type
  node_desired_size   = var.node_desired_size
  node_min_size       = var.node_min_size
  node_max_size       = var.node_max_size
}

module "postgres" {
  source = "./modules/postgres"

  cluster_name           = var.cluster_name
  vpc_id                 = aws_vpc.wake.id
  private_subnet_ids     = aws_subnet.private[*].id
  eks_security_group_id  = module.eks.cluster_security_group_id
  instance_class         = var.postgres_instance_class
  allocated_storage_gb   = var.postgres_allocated_storage_gb
}

# Backup bucket — pgBackRest writes here
resource "aws_s3_bucket" "backup" {
  bucket = var.backup_s3_bucket
}

resource "aws_s3_bucket_versioning" "backup" {
  bucket = aws_s3_bucket.backup.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
