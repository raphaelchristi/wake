# Wake on GCP — Terraform reference

Reference implementation for deploying Wake on Google Cloud via GKE Autopilot + Cloud SQL + GCS. **Reference, not turnkey**.

## Architecture

```
                ┌────────────────────────────────────────┐
   Internet ──→ │ Cloud Load Balancer (HTTPS, optional)  │
                └────────────────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────┐
                │ GKE Autopilot cluster     │
                │   Wake Helm chart:        │
                │   - wake-api Deployment   │
                │   - wake-worker Deployment│
                │   - wake-frontend         │
                │   - pgbackrest CronJob    │
                └───────────────────────────┘
                          │              │
                  Workload Identity   private VPC peering
                          │              │
                          ▼              ▼
                  [Cloud SQL]      [GCS bucket]
                  Postgres 16      (Backups)
```

## Resources

| Resource | Purpose |
|---|---|
| VPC + subnet (primary + 2 secondary ranges) | Network |
| Cloud NAT | Private subnet egress |
| GKE Autopilot cluster | Compute (managed) |
| Cloud SQL Postgres 16 (private IP) | Wake event log |
| Secret Manager secret | Postgres credentials |
| GCS bucket (versioned + 30-day lifecycle) | pgBackRest |
| Workload Identity | Pod → GCP IAM |

## Quick start

### Prereqs

- `terraform` ≥ 1.6
- `gcloud` CLI authenticated (`gcloud auth login` + `gcloud auth application-default login`)
- `kubectl` + `helm`

### Deploy

```bash
cd terraform/gcp

# Configure project + globally-unique bucket
export TF_VAR_project_id="my-gcp-project"
export TF_VAR_backup_bucket="wake-prod-backup-$(uuidgen | tr A-Z a-z | head -c 8)"
export TF_VAR_region="us-central1"

terraform init
terraform plan
terraform apply

# Configure kubectl
$(terraform output -raw kubeconfig_cmd)

# Install Wake
helm install wake ../../deploy/helm/wake \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set api.replicas=2 \
  --set worker.replicas=3 \
  --set postgres.embedded.enabled=false \
  --set postgres.external.connectionName="$(terraform output -raw postgres_connection_name)" \
  --set backup.enabled=true \
  --set backup.repositoryId="$(terraform output -raw cluster_name)" \
  --set backup.s3.bucket="$(terraform output -raw backup_bucket_name)" \
  --set backup.s3.endpoint="https://storage.googleapis.com"
```

Note: pgBackRest configured to use GCS via S3-compatible interop API.

### Tear down

```bash
helm uninstall wake
terraform destroy
```

⚠️ `deletion_protection = true` em Cloud SQL — desativar manualmente antes de destroy:
```bash
gcloud sql instances patch wake-prod-postgres --no-deletion-protection
```

## Cost estimate (us-central1, monthly)

| Component | Cost |
|---|---|
| GKE Autopilot (~3 pods worth of CPU/RAM) | ~$70 |
| Cloud SQL db-custom-2-7680 + 100GB SSD | ~$120 |
| Cloud NAT | ~$45 |
| GCS storage (10GB backups) | ~$0.20 |
| Egress 100GB | ~$12 |
| **Total baseline** | **~$250/mo** |

GKE Autopilot é pay-per-pod-resource (mais barato pra cargas variáveis); Standard mode com 3 nodes e2-standard-4 = ~$200/mo extras.

## Customization

### Standard mode (vs Autopilot)

Set `var.use_autopilot = false`. Adds explicit node pool with autoscaling 2-10 nodes.

### Multi-region

`google_sql_database_instance.wake` precisa `availability_type = "REGIONAL"` + replication. Adds ~$120/mo.

### Production hardening

- [ ] VPC Service Controls perimeter
- [ ] Org policy: enforce `iam.allowedPolicyMemberDomains`
- [ ] Workload Identity Federation (no JSON keys)
- [ ] Binary Authorization (cosign verification)
- [ ] Cloud Armor for ingress
- [ ] Cloud KMS-encrypted disks (CMEK)
- [ ] Confidential Computing nodes (optional)

## Benchmarks

`docs/BENCHMARKS.md` for Wake on this stack.

## Reference

`docs/REFERENCE-ARCH-GCP.md`.
