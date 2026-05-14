variable "aws_region" {
  description = "AWS region for Wake deployment."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "Unique name for the EKS cluster."
  type        = string
  default     = "wake-prod"
}

variable "vpc_cidr" {
  description = "CIDR block for the Wake VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.31"
}

variable "node_instance_type" {
  description = "EC2 instance type for worker nodes."
  type        = string
  default     = "t3.large"
}

variable "node_desired_size" {
  description = "Desired worker node count."
  type        = number
  default     = 3
}

variable "node_min_size" {
  description = "Minimum worker node count (autoscaling)."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum worker node count (autoscaling)."
  type        = number
  default     = 10
}

variable "postgres_instance_class" {
  description = "RDS instance class for Wake Postgres."
  type        = string
  default     = "db.t3.medium"
}

variable "postgres_allocated_storage_gb" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 100
}

variable "backup_s3_bucket" {
  description = "S3 bucket for pgBackRest backups (must be globally unique)."
  type        = string
}

variable "wake_helm_values" {
  description = "Optional Helm values overrides applied on top of the chart defaults."
  type        = any
  default     = {}
}

variable "tags" {
  description = "Common tags applied to all AWS resources."
  type        = map(string)
  default = {
    project   = "wake"
    managed_by = "terraform"
  }
}
