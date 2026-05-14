variable "cluster_name" { type = string }
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "eks_security_group_id" { type = string }
variable "instance_class" { type = string }
variable "allocated_storage_gb" { type = number }

resource "aws_db_subnet_group" "wake" {
  name       = "${var.cluster_name}-pg-subnet"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "wake_pg" {
  name        = "${var.cluster_name}-pg-sg"
  description = "Allow Postgres from EKS"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "random_password" "wake_pg" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "wake_pg" {
  name = "${var.cluster_name}-postgres-credentials"
}

resource "aws_secretsmanager_secret_version" "wake_pg" {
  secret_id = aws_secretsmanager_secret.wake_pg.id
  secret_string = jsonencode({
    username = "wake"
    password = random_password.wake_pg.result
  })
}

resource "aws_db_instance" "wake" {
  identifier             = "${var.cluster_name}-postgres"
  engine                 = "postgres"
  engine_version         = "16.4"
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage_gb
  storage_encrypted      = true
  storage_type           = "gp3"
  db_name                = "wake"
  username               = "wake"
  password               = random_password.wake_pg.result
  db_subnet_group_name   = aws_db_subnet_group.wake.name
  vpc_security_group_ids = [aws_security_group.wake_pg.id]
  skip_final_snapshot    = false
  final_snapshot_identifier = "${var.cluster_name}-final"
  backup_retention_period = 7
  multi_az               = false
  publicly_accessible    = false

  lifecycle {
    ignore_changes = [password]  # rotate via Secrets Manager rotation
  }
}

terraform {
  required_providers {
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

output "endpoint" { value = aws_db_instance.wake.endpoint }
output "secret_name" { value = aws_secretsmanager_secret.wake_pg.name }
