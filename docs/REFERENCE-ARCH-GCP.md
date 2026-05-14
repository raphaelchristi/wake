# Wake Reference Architecture — GCP

End-to-end deploy walkthrough for Wake on Google Cloud via Terraform + Helm.

> Companion to `terraform/gcp/README.md`.

## Topology

```
                       Internet
                          │
                          ▼
                  ┌────────────────────┐
                  │ Cloud DNS          │
                  └────────────────────┘
                          │
                          ▼
                  ┌──────────────────────────┐
                  │ Cloud Load Balancer      │
                  │   - HTTPS termination    │
                  │   - Google-managed cert  │
                  │   - URL maps             │
                  └──────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────────┐
        │ GKE Autopilot (private cluster)     │
        │                                     │
        │  ┌──────────┐  ┌──────────────┐    │
        │  │ wake-api │  │ wake-worker  │    │
        │  │ Deploy×3 │  │ Deploy×3-10  │    │
        │  └────┬─────┘  └──────┬───────┘    │
        │       │               │             │
        │  ┌────┴───────────────┴──────────┐ │
        │  │  Workload Identity → GCP IAM  │ │
        │  └───────────────────────────────┘ │
        │                                     │
        │  ┌──────────┐  ┌──────────────┐    │
        │  │ frontend │  │ pgbackrest   │    │
        │  │ Deploy×2 │  │ CronJob      │    │
        │  └──────────┘  └──────┬───────┘    │
        └─────────────────────────│───────────┘
                                  │
                ┌─────────────────┴───────────────┐
                │                                 │
                ▼                                 ▼
         ┌──────────────┐                  ┌──────────────┐
         │  Cloud SQL   │                  │ GCS bucket   │
         │ Postgres 16  │                  │ (backups)    │
         │ private IP   │                  │ versioning ON│
         │ PITR enabled │                  │ lifecycle 30d│
         └──────────────┘                  └──────────────┘
```

## Why GCP for Wake

| Aspect | GCP advantage |
|---|---|
| Autopilot | Zero-ops node management; pay only for pod resources |
| Cloud SQL | PITR enabled by default; private IP only via VPC peering |
| Workload Identity | First-class pod → IAM mapping (no JSON keys) |
| Anthos Config Management | GitOps-native if you use ACM |
| Confidential Computing | Optional encrypted memory + attestation |

vs AWS:
- GKE Autopilot mais barato pra cargas variáveis (pay-per-pod)
- Cloud SQL PITR built-in (RDS exige Multi-AZ pra similar)
- IAM model mais granular (custom roles), mas mais verboso

## Sizing

| Scale | GKE | Cloud SQL | Monthly |
|---|---|---|---|
| Dev | Autopilot (~3 pods × small) | db-f1-micro | ~$80 |
| Small prod | Autopilot (~10 pods) | db-custom-2-7680 | ~$220 |
| Medium | Autopilot (autoscale) | db-custom-4-16384 | ~$450 |
| Large | Standard regional (HA) | db-custom-8-32768 MA | ~$1200 |

## TLS

Google-managed cert simplest:

```yaml
apiVersion: networking.gke.io/v1
kind: ManagedCertificate
metadata: { name: wake-cert }
spec:
  domains: [wake.example.com]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    networking.gke.io/managed-certificates: wake-cert
    kubernetes.io/ingress.global-static-ip-name: wake-ip
```

## DNS

```bash
gcloud dns record-sets transaction start --zone=example-com
gcloud dns record-sets transaction add 35.x.x.x \
  --name=wake.example.com. --ttl=300 --type=A --zone=example-com
gcloud dns record-sets transaction execute --zone=example-com
```

## Workload Identity setup

```bash
# Create GCP SA
gcloud iam service-accounts create wake-api \
  --display-name="Wake API service account"

# Grant access to Secret Manager (for Postgres password)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:wake-api@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Bind k8s SA → GCP SA
gcloud iam service-accounts add-iam-policy-binding \
  wake-api@$PROJECT_ID.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:$PROJECT_ID.svc.id.goog[wake/wake-api]"

# Annotate k8s SA
kubectl annotate serviceaccount wake-api -n wake \
  iam.gke.io/gcp-service-account=wake-api@$PROJECT_ID.iam.gserviceaccount.com
```

Wake API pod can now read Secrets Manager + GCS without static creds.

## Operational runbook

### Daily

- `gcloud monitoring dashboards list --filter="displayName:Wake"`
- Cloud SQL Insights dashboard

### Weekly

- Backup drill: `scripts/restore-drill.sh`
- Review GKE node upgrade window (default Sunday 02:00 PT)

### Monthly

- Patch GKE Kubernetes version (release channel auto)
- Rotate Cloud SQL password via Secret Manager
- Review IAM audit logs in Cloud Logging

### Quarterly

- Cross-region disaster recovery drill
- Security audit (SECURITY.md checklist)
- VPC Flow Logs review

## DR

GCS is multi-region by default (when bucket in `region` with replication on). For full DR:

1. Stand up Wake in second region:
   ```bash
   TF_VAR_region=europe-west1 terraform apply
   ```
2. Cloud SQL backup can be exported + imported cross-region (slower than AWS):
   ```bash
   gcloud sql instances clone wake-prod-postgres wake-dr-postgres \
     --point-in-time="2026-05-14T10:00:00Z"
   ```
3. Restore via pgBackRest from GCS bucket (S3-compat interop)
4. Update DNS

RTO realistic: 1-2 hours em GCP (slower than AWS RDS snapshot copy in some scenarios).

## Compliance

- **SOC 2**: GKE + Cloud SQL + GCS in scope
- **HIPAA**: BAA via Google; Healthcare Data Plane available
- **GDPR**: region selection enforces data residency
- **FedRAMP**: GovCloud-equivalent (Assured Workloads)

## Migrating

This Terraform is **reference**. Customize:
1. Fork into your infra repo
2. Add VPC Service Controls perimeter
3. Replace random naming with org convention
4. Add Binary Authorization (cosign verification)
5. Integrate Anthos Config Management if you use it
6. Wire to your IdP via Cloud Identity / Google Workspace SSO

## Reference

- GKE Best Practices: https://cloud.google.com/kubernetes-engine/docs/best-practices
- Cloud SQL Best Practices: https://cloud.google.com/sql/docs/postgres/best-practices
- Workload Identity: https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity
