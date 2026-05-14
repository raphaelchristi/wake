output "cluster_name" {
  description = "GKE cluster name."
  value       = module.gke.cluster_name
}

output "cluster_endpoint" {
  description = "GKE master endpoint."
  value       = module.gke.endpoint
  sensitive   = true
}

output "cluster_ca_cert" {
  description = "GKE cluster CA certificate (base64)."
  value       = module.gke.ca_cert
  sensitive   = true
}

output "postgres_connection_name" {
  description = "Cloud SQL connection name (used by Cloud SQL Auth Proxy)."
  value       = module.postgres.connection_name
}

output "postgres_private_ip" {
  description = "Cloud SQL private IP."
  value       = module.postgres.private_ip
  sensitive   = true
}

output "postgres_secret_name" {
  description = "Secret Manager secret holding Postgres credentials."
  value       = module.postgres.secret_name
}

output "backup_bucket_name" {
  description = "GCS bucket for pgBackRest."
  value       = google_storage_bucket.backup.name
}

output "kubeconfig_cmd" {
  description = "Command to fetch kubeconfig."
  value       = "gcloud container clusters get-credentials ${module.gke.cluster_name} --region ${var.region} --project ${var.project_id}"
}
