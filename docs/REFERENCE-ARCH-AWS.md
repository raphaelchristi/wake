# Wake Reference Architecture — AWS

End-to-end deploy walkthrough for Wake on AWS via Terraform + Helm.

> Companion to `terraform/aws/README.md`. This doc adds rationale, tradeoffs, and operational guidance.

## Topology overview

```
                       Internet
                          │
                          ▼
                  ┌──────────────┐
                  │ Route 53 DNS │
                  └──────────────┘
                          │
                          ▼
                  ┌──────────────────┐
                  │ ACM cert (TLS)   │
                  └──────────────────┘
                          │
                          ▼
                  ┌──────────────────────┐
                  │ AWS LBC (ALB)        │
                  │ /        → frontend  │
                  │ /api     → wake-api  │
                  │ /metrics → wake-api  │
                  └──────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────────┐
        │ EKS Cluster (private API endpoint   │
        │ + restricted public via CIDR)       │
        │                                     │
        │  ┌──────────┐  ┌──────────────┐    │
        │  │ wake-api │  │ wake-worker  │    │
        │  │ Deploy×3 │  │ Deploy×3-10  │    │
        │  └────┬─────┘  └──────┬───────┘    │
        │       │               │             │
        │  ┌────┴───────────────┴──────────┐ │
        │  │  Wake event log + sandbox     │ │
        │  └───────────────────────────────┘ │
        │                                     │
        │  ┌──────────┐  ┌──────────────┐    │
        │  │ frontend │  │ pgbackrest   │    │
        │  │ Deploy×2 │  │ CronJob      │    │
        │  └──────────┘  └──────┬───────┘    │
        └─────────────────────────│───────────┘
                                  │
                ┌─────────────────┴───────────────┐
                ▼                                 ▼
         ┌──────────────┐                  ┌──────────────┐
         │ RDS Postgres │                  │  S3 bucket    │
         │ 16 (1 AZ)    │                  │ (backups)     │
         │ Multi-AZ opt │                  │ versioning ON │
         └──────────────┘                  └──────────────┘
```

## Why these AWS services

| Choice | Why | Alternative |
|---|---|---|
| EKS (managed) | Reduces undifferentiated ops; AWS handles control plane | ECS (Fargate) — simpler but no Helm |
| RDS Postgres | Managed backup, encrypted, easy Multi-AZ | Self-host Postgres on EKS — more ops |
| S3 | Cheap, durable, native pgBackRest support | EFS — slow, expensive for backups |
| AWS LBC (ALB) | Native HTTP routing + ACM TLS | NLB + nginx ingress — more layers |
| Workload Identity (IRSA) | Pod-level IAM without static creds | Static keys — anti-pattern |
| Secrets Manager | Auto-rotation for RDS creds | SSM Parameter Store — no rotation hook |

## Sizing recommendations

| Scale | API replicas | Workers | RDS class | Notes |
|---|---|---|---|---|
| Dev / single team | 1 | 1 | db.t3.small | $150/mo |
| Small prod (≤100 sessions/day) | 2 | 2 | db.t3.medium | $300/mo |
| Medium (≤1k sessions/day) | 3 | 5 | db.r6g.large | $700/mo |
| Large (≤10k sessions/day) | 5+ HPA | 10+ HPA | db.r6g.xlarge Multi-AZ | $2k/mo |

Wake benchmarks suportam linear scaling até 1000 concurrent sessions (k6 results em `docs/BENCHMARKS.md`).

## TLS termination

Recommendation: ACM cert + AWS LBC ALB. Annotate Ingress:

```yaml
metadata:
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123:certificate/abc
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
    alb.ingress.kubernetes.io/healthcheck-path: /health
```

## DNS

```bash
aws route53 change-resource-record-sets --hosted-zone-id Z123 --change-batch '{
  "Changes": [{
    "Action": "CREATE",
    "ResourceRecordSet": {
      "Name": "wake.example.com",
      "Type": "A",
      "AliasTarget": {
        "HostedZoneId": "<alb-hosted-zone>",
        "DNSName": "<alb-dns-name>",
        "EvaluateTargetHealth": false
      }
    }
  }]
}'
```

## Operational runbook

### Daily

- Check `wake_sessions_total` Prom counter trends
- Verify pgBackRest CronJob succeeded (`kubectl get cronjob -n wake`)

### Weekly

- Run `scripts/restore-drill.sh` — validates RTO < 30min
- Review `wake_errors_total{code}` top labels
- Rotate `WAKE_API_KEY` via Helm upgrade

### Monthly

- Audit IAM Access Advisor — remove unused permissions
- Review CloudWatch costs + S3 backup growth
- Patch EKS Kubernetes version (latest in release channel)
- Rotate RDS password via Secrets Manager

### Quarterly

- Disaster recovery drill end-to-end (cluster destroy + restore from backup)
- Security audit: review SECURITY.md hardening checklist
- Cost optimization review

## Disaster recovery procedure

If primary region down:

1. **Stand up new cluster** in target region:
   ```bash
   cd terraform/aws
   TF_VAR_aws_region=us-west-2 terraform apply
   ```
2. **Restore from S3 backup** (cross-region readable):
   ```bash
   helm install wake ../../deploy/helm/wake \
     --set backup.enabled=true \
     --set backup.restoreTest.enabled=true \
     --set backup.s3.bucket=wake-prod-backup-xxx
   ```
3. **Verify event log integrity**: `wake events show <session-id> --from-restore`
4. **Update DNS** to new ALB
5. **Communicate to customers** (RTO target: 30 min)

## Cost optimization

- Use **Savings Plans** for EC2 (1-yr commit = ~30% off)
- **Spot instances** for worker pool (set `min_size > 0` for baseline)
- **S3 Intelligent-Tiering** for backups older than 30 days
- **Aurora Serverless v2** instead of RDS for variable workload (pay-per-use, but cold-start)
- **NAT instance** (not gateway) for low-egress envs (~$30/mo vs $135/mo)

## Compliance notes

- **SOC 2**: EKS + RDS + S3 all SOC 2 compliant
- **HIPAA**: enable Healthcare Data Plane on RDS; sign BAA with AWS
- **GDPR**: data residency via region selection; backup bucket in same region
- **PCI DSS**: needs additional CloudHSM + IAM hardening — out of scope here

## Migrating from this ref to fully custom

This Terraform is a **reference**. For production:

1. Fork into your own infra repo
2. Pin provider versions to your standard
3. Replace placeholder names with your conventions
4. Add your tagging strategy
5. Integrate with your secret manager
6. Add your observability stack (Datadog/New Relic/CloudWatch dashboards)
7. Connect to your IdP for EKS RBAC (AWS IAM via aws-iam-authenticator)

## Reference

- AWS Well-Architected Framework: https://aws.amazon.com/architecture/well-architected/
- EKS Best Practices: https://aws.github.io/aws-eks-best-practices/
- RDS Postgres tuning: see `docs/BENCHMARKS.md`
