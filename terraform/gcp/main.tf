provider "google" {
  project = var.project_id
  region  = var.region
}

# -----------------------------------------------------------------------------
# VPC + Subnet (single subnet with secondary ranges for pods/services)
# -----------------------------------------------------------------------------

resource "google_compute_network" "wake" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "wake" {
  name          = "${var.cluster_name}-subnet"
  ip_cidr_range = var.vpc_cidr_primary
  network       = google_compute_network.wake.id
  region        = var.region

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.vpc_cidr_pods
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.vpc_cidr_services
  }

  private_ip_google_access = true
}

resource "google_compute_router" "wake" {
  name    = "${var.cluster_name}-router"
  region  = var.region
  network = google_compute_network.wake.id
}

resource "google_compute_router_nat" "wake" {
  name                               = "${var.cluster_name}-nat"
  router                             = google_compute_router.wake.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# -----------------------------------------------------------------------------
# GKE + Cloud SQL (module-delegated)
# -----------------------------------------------------------------------------

module "gke" {
  source = "./modules/gke"

  cluster_name       = var.cluster_name
  region             = var.region
  kubernetes_version = var.kubernetes_version
  network_id         = google_compute_network.wake.id
  subnet_id          = google_compute_subnetwork.wake.id
  use_autopilot      = var.use_autopilot
  node_machine_type  = var.node_machine_type
}

module "postgres" {
  source = "./modules/postgres"

  project_id   = var.project_id
  region       = var.region
  cluster_name = var.cluster_name
  network_id   = google_compute_network.wake.id
  tier         = var.postgres_tier
  disk_gb      = var.postgres_disk_gb
}

# Backup bucket — pgBackRest
resource "google_storage_bucket" "backup" {
  name                        = var.backup_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  versioning { enabled = true }

  lifecycle_rule {
    condition { age = 30 }
    action    { type = "Delete" }
  }
}
