# Wake on AWS — Terraform reference

Reference implementation for deploying Wake on AWS via EKS + RDS + S3. **Reference, not turnkey**: clone, audit, adapt.

## Architecture

```
                ┌────────────────────────────────────────┐
   Internet ──→ │ ALB (managed by AWS LBC, optional)     │
                └────────────────────────────────────────┘
                                │
                ┌───────────────┴──────────────┐
                ▼                              ▼
           [public subnets x3]            [NAT egress]
                │
                ▼
           [private subnets x3] ─→ [EKS worker nodes]
                                        │
                                        ▼
                ┌──────────────────────────────────┐
                │ Wake Helm chart:                 │
                │   - wake-api (Deployment)        │
                │   - wake-worker (Deployment)     │
                │   - wake-frontend (Deployment)   │
                │   - pgbackrest CronJob (backup)  │
                └──────────────────────────────────┘
                                        │
                                        ▼
                              [RDS Postgres 16]    [S3 bucket]
                              (Wake event log)     (Backups)
```

## Resources created

| Resource | Purpose |
|---|---|
| VPC + 6 subnets (3 public, 3 private) | Network isolation |
| 3 NAT gateways | Private subnet egress |
| EKS cluster (1.31) + managed node group | Compute |
| EKS IAM roles (cluster + node) | RBAC |
| RDS Postgres 16 (Multi-AZ optional) | Wake event log |
| RDS Secrets Manager secret | Postgres credentials |
| S3 bucket (versioned + encrypted) | pgBackRest backups |

## Quick start

### Prereqs

- `terraform` ≥ 1.6
- `aws` CLI configured (`aws configure`)
- `kubectl` + `helm`

### Deploy

```bash
cd terraform/aws

# Set globally-unique S3 bucket name + region
export TF_VAR_backup_s3_bucket="wake-prod-backup-$(uuidgen | tr A-Z a-z | head -c 8)"

terraform init
terraform plan
terraform apply

# Configure kubectl
$(terraform output -raw kubeconfig_cmd)

# Install Wake Helm chart
helm install wake ../../deploy/helm/wake \
  --set auth.apiKey="$(openssl rand -hex 32)" \
  --set auth.oauthStateSecret="$(openssl rand -hex 32)" \
  --set api.replicas=2 \
  --set worker.replicas=3 \
  --set postgres.embedded.enabled=false \
  --set postgres.external.url="$(terraform output -raw postgres_endpoint)" \
  --set backup.enabled=true \
  --set backup.repositoryId="$(terraform output -raw cluster_name)" \
  --set backup.s3.bucket="$(terraform output -raw backup_bucket_name)" \
  --set backup.s3.region="$(terraform output -raw aws_region 2>/dev/null || echo us-east-1)"
```

### Tear down

```bash
helm uninstall wake
terraform destroy
```

⚠️ `terraform destroy` does NOT delete the S3 backup bucket if it has objects. Empty it manually first if you want full cleanup.

## Cost estimate (us-east-1, monthly)

| Component | Cost |
|---|---|
| EKS control plane | $73 |
| 3× t3.large EC2 (24/7) | $200 |
| 3× NAT Gateway + 100GB egress | $135 |
| RDS db.t3.medium + 100GB storage + Multi-AZ off | $80 |
| S3 storage (10GB backups + retrieval) | $5 |
| **Total baseline** | **~$493/mo** |

Pareback options:
- Drop NAT gateways → use NAT instances → ~$30/mo savings (less reliable)
- Single-AZ RDS → already default → save by keeping
- Spot EC2 for workers → ~$80/mo savings (eviction risk)
- Fargate for variable workload → pay-per-use (better for low-volume)

## Customization

### Override Helm values

`var.wake_helm_values` (type `any`) — passed through. Example:

```hcl
wake_helm_values = {
  api = {
    replicas = 5
    resources = {
      requests = { cpu = "500m", memory = "512Mi" }
      limits   = { cpu = "1500m", memory = "1Gi" }
    }
  }
}
```

### Multi-AZ Postgres

Set `multi_az = true` in `modules/postgres/main.tf`. Adds ~$80/mo for HA.

### Production hardening checklist

- [ ] Enable VPC Flow Logs to S3
- [ ] CloudTrail multi-region for audit
- [ ] AWS Config rules for compliance
- [ ] KMS-encrypted RDS storage (custom key)
- [ ] Restrict EKS public endpoint to specific CIDRs
- [ ] Pod Security Standards `restricted` profile
- [ ] AWS Load Balancer Controller for ALB ingress
- [ ] cert-manager + ACME for TLS
- [ ] External secrets operator (read from Secrets Manager)
- [ ] Backup S3 bucket replication to second region

## Benchmarks

See `docs/BENCHMARKS.md` for Wake performance on this stack.

## Troubleshooting

**EKS subnet tagging**: `kubernetes.io/cluster/<name> = shared` required for AWS LBC to route. Already set in `main.tf`.

**RDS connection refused**: ensure RDS SG allows EKS cluster SG (default behavior in `modules/postgres/main.tf`).

**Helm install times out**: EKS DNS slow to propagate. Wait 60s after `terraform apply`, then `kubectl get nodes` before installing.

## Reference

Full deploy walkthrough: `docs/REFERENCE-ARCH-AWS.md`.
