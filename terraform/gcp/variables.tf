variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "Name of the GKE cluster."
  type        = string
  default     = "wake-prod"
}

variable "vpc_cidr_primary" {
  description = "Primary IP range for the Wake VPC."
  type        = string
  default     = "10.30.0.0/20"
}

variable "vpc_cidr_pods" {
  description = "Secondary IP range for GKE pods."
  type        = string
  default     = "10.40.0.0/14"
}

variable "vpc_cidr_services" {
  description = "Secondary IP range for GKE services."
  type        = string
  default     = "10.44.0.0/20"
}

variable "kubernetes_version" {
  description = "GKE Kubernetes minimum version (Autopilot follows release channel)."
  type        = string
  default     = "1.31"
}

variable "node_machine_type" {
  description = "Standard mode: GCE machine type."
  type        = string
  default     = "e2-standard-4"
}

variable "use_autopilot" {
  description = "Use GKE Autopilot (recommended) vs Standard."
  type        = bool
  default     = true
}

variable "postgres_tier" {
  description = "Cloud SQL tier for Postgres."
  type        = string
  default     = "db-custom-2-7680"  # 2 vCPU, 7.5GB
}

variable "postgres_disk_gb" {
  description = "Cloud SQL disk size GB."
  type        = number
  default     = 100
}

variable "backup_bucket" {
  description = "GCS bucket for pgBackRest backups (must be globally unique)."
  type        = string
}

variable "labels" {
  description = "Common labels applied to resources."
  type        = map(string)
  default = {
    project    = "wake"
    managed_by = "terraform"
  }
}
