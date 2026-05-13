# Deploy: AWS

Production-grade enterprise deployment on AWS. Two supported topologies:

1. **EKS + RDS** — full Helm chart on EKS, RDS for Postgres, ElastiCache for Redis.
2. **ECS Fargate + RDS** — managed containers, no K8s, simpler ops at the cost of feature parity.

Pick **EKS** if you already run Kubernetes; **ECS** if you don't.

## A. EKS topology

### A.1 Cluster

```bash
eksctl create cluster --name wake-prod --region us-east-1 \
  --node-type m6i.large --nodes 3 --nodes-min 3 --nodes-max 10 \
  --with-oidc --managed
```

### A.2 RDS Postgres

Pick a generation with logical replication enabled for downstream
analytics:

```bash
aws rds create-db-instance \
  --db-instance-identifier wake-prod \
  --db-instance-class db.r6.large \
  --engine postgres --engine-version 16 \
  --allocated-storage 200 --storage-type gp3 \
  --master-username wake --master-user-password "$(openssl rand -hex 16)" \
  --db-name wake \
  --vpc-security-group-ids sg-... \
  --backup-retention-period 14
```

Apply the parameter group tweaks Wake needs:

```ini
max_connections = 200
shared_buffers = 4GB
work_mem = 32MB
maintenance_work_mem = 256MB
checkpoint_completion_target = 0.9
wal_compression = on
```

### A.3 ElastiCache Redis

```bash
aws elasticache create-replication-group \
  --replication-group-id wake-prod \
  --engine redis --cache-node-type cache.t4g.small \
  --num-cache-clusters 2 \
  --automatic-failover-enabled
```

### A.4 Secrets Manager

Stash secrets so the cluster pulls them via External Secrets Operator
or IRSA-backed env injection:

```bash
aws secretsmanager create-secret --name wake/prod/db \
  --secret-string '{"password":"..."}'
aws secretsmanager create-secret --name wake/prod/anthropic \
  --secret-string '{"api_key":"sk-ant-..."}'
```

### A.5 Helm install

```bash
helm install wake ./deploy/helm/wake --namespace wake --create-namespace \
  --set postgres.enabled=false \
  --set redis.enabled=false \
  --set api.replicas=4 \
  --set worker.replicas=10 \
  --set worker.concurrency=8 \
  --set secrets.existingSecret=wake-secrets-external \
  --set ingress.enabled=true \
  --set ingress.className=alb \
  --set ingress.annotations."kubernetes\.io/ingress\.class"=alb \
  --set ingress.hosts[0].host=wake.your-corp.com
```

Provide `WAKE_DATABASE_URL` / `WAKE_REDIS_URL` via the external
secret. Ingress class `alb` routes through AWS Load Balancer
Controller for managed ALB ingress.

### A.6 Networking

- Run the cluster in private subnets.
- Restrict RDS / Redis security groups to the cluster's pod security
  group.
- Route egress through a NAT Gateway; agentgateway's `allowed_hosts`
  prevents accidental data exfiltration.
- Optional: VPC Endpoints for `bedrock-runtime` if you're targeting
  Bedrock via LiteLLM.

## B. ECS Fargate topology

### B.1 Cluster

```bash
aws ecs create-cluster --cluster-name wake-prod
```

### B.2 Task definitions

Two task definitions: `wake-api` and `wake-worker`. Both use the same
image (`wake-ai/wake:0.4.0`) with different command lines.

`wake-api` essentials:

```json
{
  "family": "wake-api",
  "containerDefinitions": [{
    "name": "api",
    "image": "<ecr>/wake-ai/wake:0.4.0",
    "command": ["server", "--host", "0.0.0.0", "--port", "8080"],
    "portMappings": [{"containerPort": 8080}],
    "environment": [
      {"name": "WAKE_DATABASE_URL", "value": "..."},
      {"name": "WAKE_REDIS_URL", "value": "..."},
      {"name": "WAKE_AGENTGATEWAY_URL", "value": "http://agentgateway.wake.local:8888"}
    ],
    "secrets": [
      {"name": "ANTHROPIC_API_KEY", "valueFrom": "arn:aws:secretsmanager:..."},
      {"name": "OPENAI_API_KEY",    "valueFrom": "arn:aws:secretsmanager:..."}
    ]
  }],
  "cpu": "1024",
  "memory": "2048",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"]
}
```

`wake-worker` mirrors it but the command is `["worker", "--concurrency", "4"]`.

### B.3 Service

```bash
aws ecs create-service --cluster wake-prod \
  --service-name wake-api --task-definition wake-api \
  --desired-count 3 --launch-type FARGATE \
  --load-balancers targetGroupArn=...,containerName=api,containerPort=8080 \
  --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}"
```

Repeat for `wake-worker` (no load balancer).

### B.4 Service discovery

Use AWS Cloud Map or App Mesh so workers and the API resolve
`postgres`, `redis`, `agentgateway`, `vault` by name without an ELB
per service.

### B.5 Auto scaling

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs --resource-id service/wake-prod/wake-worker \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 3 --max-capacity 30
```

Scale on `CPUUtilization` average ≥ 70.

## C. Cost notes

Rough monthly USD (us-east-1, on-demand):

| Workload | EKS path | ECS path |
|----------|----------|----------|
| Cluster control plane | $73 | $0 |
| Compute (3 m6i.large) | $230 | $200 (1024 cpu/2GB Fargate × 6 tasks) |
| RDS db.r6.large multi-AZ | $200 | $200 |
| ElastiCache cache.t4g.small | $30 | $30 |
| ALB + NAT GW | $40 | $40 |
| Secrets Manager | $5 | $5 |
| **Total** | **~$580** | **~$475** |

Don't add the OIDC / Anthropic API costs to this — those scale with usage.

## D. Compliance

- Wake events / payloads can contain PII — enable RDS at-rest encryption
  + IAM authentication, and consider Aurora's logical replication if
  you ship events to a downstream warehouse.
- Vault: Infisical supports SOC2 deployment patterns. The cross-zone
  encryption key (`ENCRYPTION_KEY`) must come from KMS in production.
- agentgateway's `allowed_hosts` + audit log doubles as a compliance
  artefact (proof of egress filtering).
