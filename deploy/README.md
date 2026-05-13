# deploy/

Production deployment artefacts for Wake.

## Layout

```
deploy/
├── Dockerfile                       # multistage build (api + worker)
├── docker-compose.yml               # full Phase 4 stack on one host
├── docker-compose.dev.yml           # overlay for hot reload
├── agentgateway/config.yaml         # sidecar egress proxy config
├── helm/wake/                       # Helm chart (Chart.yaml, values.yaml, templates/)
└── README.md                        # this file
```

## Quick start — Docker Compose

```bash
cd deploy
docker compose up -d
curl http://localhost:8080/health
docker compose logs -f wake-api wake-worker
```

Scaling workers:

```bash
docker compose up -d --scale wake-worker=4
```

## Quick start — Helm

```bash
cd deploy
helm install wake ./helm/wake \
  --set secrets.anthropicApiKey=$ANTHROPIC_API_KEY \
  --set vault.encryptionKey=$(openssl rand -hex 16) \
  --set vault.authSecret=$(openssl rand -base64 32)

kubectl get pods -l app.kubernetes.io/instance=wake
kubectl port-forward svc/wake-api 8080:8080
```

## What's in the stack

| Component        | Role | Image |
|------------------|------|-------|
| wake-api         | FastAPI / SSE | `wake-ai/wake:0.4.0` |
| wake-worker      | Harness worker | `wake-ai/wake:0.4.0` |
| postgres         | Event store + advisory locks | `postgres:16` |
| redis            | Pub/sub fan-out | `redis:7-alpine` |
| agentgateway     | Egress proxy / MCP routing | `ghcr.io/agentgateway/agentgateway:latest` |
| infisical-vault  | Credential vault | `infisical/infisical:latest` |

## Topology

```
client ──HTTP──▶ wake-api ──SQL──▶ postgres
                  │
                  └─ Redis pub/sub ──▶ wake-worker(s)
                                          │
                                          └─ egress ─▶ agentgateway ──▶ external API
                                                          │
                                                          └─ vault refs ─▶ infisical-vault
```

Multi-worker correctness relies on Postgres advisory locks (`pg_try_advisory_lock`).
A worker holding a session's lock receives notifications via Redis pub/sub; the
heartbeat protocol (10s renew, 30s watchdog) releases the lock if the worker
dies, so another worker resumes within ~60s.

## Documentation

Detailed runbooks under `../docs/`:

- `docs/DEPLOY.md` — overview / decision matrix
- `docs/DEPLOY-DOCKER-COMPOSE.md` — single-host self-hosting
- `docs/DEPLOY-KUBERNETES.md` — Helm + minikube / GKE / EKS
- `docs/DEPLOY-FLYIO.md` — Fly.io
- `docs/DEPLOY-AWS.md` — AWS (ECS / EKS / managed Postgres)
