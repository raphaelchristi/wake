variable "project_id" { type = string }
variable "region" { type = string }
variable "cluster_name" { type = string }
variable "network_id" { type = string }
variable "tier" { type = string }
variable "disk_gb" { type = number }

resource "random_password" "wake_pg" {
  length  = 32
  special = false
}

resource "google_secret_manager_secret" "wake_pg" {
  secret_id = "${var.cluster_name}-postgres-credentials"
  replication { auto {} }
}

resource "google_secret_manager_secret_version" "wake_pg" {
  secret = google_secret_manager_secret.wake_pg.id
  secret_data = jsonencode({
    username = "wake"
    password = random_password.wake_pg.result
  })
}

# Private services access for Cloud SQL
resource "google_compute_global_address" "wake_pg" {
  name          = "${var.cluster_name}-pg-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.network_id
}

resource "google_service_networking_connection" "wake_pg" {
  network                 = var.network_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.wake_pg.name]
}

resource "google_sql_database_instance" "wake" {
  name             = "${var.cluster_name}-postgres"
  region           = var.region
  database_version = "POSTGRES_16"

  depends_on = [google_service_networking_connection.wake_pg]

  settings {
    tier              = var.tier
    disk_size         = var.disk_gb
    disk_type         = "PD_SSD"
    availability_type = "ZONAL"

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "02:00"
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }
  }

  deletion_protection = true
}

resource "google_sql_database" "wake" {
  name     = "wake"
  instance = google_sql_database_instance.wake.name
}

resource "google_sql_user" "wake" {
  name     = "wake"
  instance = google_sql_database_instance.wake.name
  password = random_password.wake_pg.result
}

terraform {
  required_providers {
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

output "connection_name" { value = google_sql_database_instance.wake.connection_name }
output "private_ip" {
  value     = google_sql_database_instance.wake.private_ip_address
  sensitive = true
}
output "secret_name" { value = google_secret_manager_secret.wake_pg.secret_id }
