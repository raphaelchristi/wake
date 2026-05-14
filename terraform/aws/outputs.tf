output "vpc_id" {
  description = "Wake VPC ID."
  value       = aws_vpc.wake.id
}

output "cluster_endpoint" {
  description = "EKS API endpoint for kubectl/Helm."
  value       = module.eks.cluster_endpoint
}

output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_certificate_authority_data" {
  description = "EKS cluster CA cert (base64)."
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "postgres_endpoint" {
  description = "RDS Postgres endpoint for Wake."
  value       = module.postgres.endpoint
}

output "postgres_secret_name" {
  description = "Secrets Manager secret holding Postgres credentials."
  value       = module.postgres.secret_name
}

output "backup_bucket_name" {
  description = "S3 bucket for pgBackRest."
  value       = aws_s3_bucket.backup.id
}

output "kubeconfig_cmd" {
  description = "Command to update local kubeconfig."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
