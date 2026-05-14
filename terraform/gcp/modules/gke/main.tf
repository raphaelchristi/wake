variable "cluster_name" { type = string }
variable "region" { type = string }
variable "kubernetes_version" { type = string }
variable "network_id" { type = string }
variable "subnet_id" { type = string }
variable "use_autopilot" { type = bool }
variable "node_machine_type" { type = string }

resource "google_container_cluster" "wake" {
  name     = var.cluster_name
  location = var.region

  network    = var.network_id
  subnetwork = var.subnet_id

  enable_autopilot = var.use_autopilot

  min_master_version = var.kubernetes_version

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
  }

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.cluster_name}.svc.id.goog"
  }

  deletion_protection = false
}

# Standard-mode node pool — only when Autopilot is disabled
resource "google_container_node_pool" "wake" {
  count = var.use_autopilot ? 0 : 1

  name     = "${var.cluster_name}-default"
  cluster  = google_container_cluster.wake.name
  location = var.region

  node_count = 3

  node_config {
    machine_type = var.node_machine_type
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    workload_metadata_config { mode = "GKE_METADATA" }
  }

  autoscaling {
    min_node_count = 2
    max_node_count = 10
  }
}

output "cluster_name" { value = google_container_cluster.wake.name }
output "endpoint" {
  value     = google_container_cluster.wake.endpoint
  sensitive = true
}
output "ca_cert" {
  value     = google_container_cluster.wake.master_auth[0].cluster_ca_certificate
  sensitive = true
}
