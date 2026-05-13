# Deploy: Kubernetes (Helm)

Production-grade deployment using the bundled Helm chart at
`deploy/helm/wake/`. Works on minikube, kind, GKE, EKS, AKS,
self-hosted, anything that's a vanilla Kubernetes cluster.

## Prerequisites

- Kubernetes ≥ 1.27
- Helm 3
- `kubectl` configured against your cluster
- A storage class that supports `ReadWriteOnce` (default in every
  managed K8s)

## 1. Install the chart

```bash
helm install wake ./deploy/helm/wake \
  --namespace wake \
  --create-namespace \
  --set secrets.anthropicApiKey=$ANTHROPIC_API_KEY \
  --set vault.encryptionKey=$(openssl rand -hex 16) \
  --set vault.authSecret=$(openssl rand -base64 32) \
  --set postgres.password=$(openssl rand -hex 16)
```

What gets created:

- `wake-api` Deployment (2 replicas, `LoadBalancer` Service by default)
- `wake-worker` Deployment (3 replicas)
- `wake-postgres` StatefulSet (1 replica, 50 GiB PVC)
- `wake-redis` Deployment
- `wake-agentgateway` Deployment + ConfigMap
- `wake-vault` Deployment (Infisical)
- `wake-secret` (passwords + API keys)
- Optional Ingress for the API tier

Verify:

```bash
kubectl -n wake get pods
kubectl -n wake port-forward svc/wake-api 8080:8080
curl http://localhost:8080/health
```

## 2. Use a managed Postgres

In production you should disable the in-cluster Postgres and point at
an RDS / Cloud SQL / managed Postgres instance:

```yaml
# values-prod.yaml
postgres:
  enabled: false
  password: ""  # ignored when disabled

api:
  replicas: 4

worker:
  replicas: 10
  concurrency: 8
```

And inject the DSN via the secret:

```bash
kubectl -n wake create secret generic wake-secret-extra \
  --from-literal=WAKE_DATABASE_URL=postgresql+asyncpg://user:pass@rds-endpoint:5432/wake

# add envFrom: wake-secret-extra to api + worker deployments
```

Then `helm upgrade wake ./deploy/helm/wake -f values-prod.yaml`.

## 3. Ingress + TLS

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: wake.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: wake-tls
      hosts:
        - wake.example.com
```

Combine with cert-manager for automatic Let's Encrypt certs.

## 4. Horizontal scaling

```bash
kubectl -n wake scale deployment wake-worker --replicas=20
kubectl -n wake scale deployment wake-api --replicas=6
```

Workers claim sessions via Postgres advisory locks (`pg_try_advisory_lock`)
so adding replicas is correct without coordinator changes.

For autoscaling, wire an HPA pointing at CPU or session-queue depth:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: wake-worker
  namespace: wake
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: wake-worker
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## 5. agentgateway

Lives as a single Deployment by default. The ConfigMap rendered from
`agentgateway.allowedHosts` + `agentgateway.mcpRoutes` is mounted
read-only at `/etc/agentgateway/config.yaml`. Edit Helm values and
`helm upgrade` to roll a new config; the pod restart picks it up.

## 6. Observability

Enable OpenTelemetry export:

```yaml
observability:
  otel:
    enabled: true
    endpoint: http://otel-collector.observability.svc:4318
```

API + worker emit OTLP traces; agentgateway exports its own via the
same endpoint.

## 7. Upgrades

```bash
helm upgrade wake ./deploy/helm/wake \
  --set image.tag=0.4.1
```

Rolling restart on api + worker. Workers in the middle of a step
release advisory locks via SIGTERM handler; a fresh worker resumes
within ≤ 60s (see `examples/05-kill-and-resume`).

## 8. minikube quickstart

```bash
minikube start --memory=4096 --cpus=4
helm install wake ./deploy/helm/wake --create-namespace --namespace wake \
  --set api.service.type=NodePort \
  --set postgres.persistence.size=10Gi
minikube service -n wake wake-api --url
```

## 9. Disabling components

For BYO services, flip the appropriate `enabled` flag:

| Component | Value | Notes |
|-----------|-------|-------|
| Postgres  | `postgres.enabled: false` | Provide `WAKE_DATABASE_URL` externally |
| Redis     | `redis.enabled: false` | Provide `WAKE_REDIS_URL` externally |
| Vault     | `vault.enabled: false` | Provide `WAKE_VAULT_URL` externally |
| agentgateway | `agentgateway.enabled: false` | Provide `WAKE_AGENTGATEWAY_URL` externally |

## 10. Sanity-check

```bash
helm lint ./deploy/helm/wake
helm template wake ./deploy/helm/wake | kubectl apply --dry-run=client -f -
```
