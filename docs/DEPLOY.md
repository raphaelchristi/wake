# Deploying Wake

Wake ships three first-class deploy targets in Phase 4:

| Target | Use when | Doc |
|--------|----------|-----|
| **Docker Compose** | Single host, self-hosted dev / staging, < 100 concurrent sessions | [DEPLOY-DOCKER-COMPOSE.md](./DEPLOY-DOCKER-COMPOSE.md) |
| **Kubernetes / Helm** | Multi-node, production HA, ≥ 100 concurrent sessions | [DEPLOY-KUBERNETES.md](./DEPLOY-KUBERNETES.md) |
| **Fly.io**  | Fast managed deploys, simple ops, edge regions | [DEPLOY-FLYIO.md](./DEPLOY-FLYIO.md) |
| **AWS** | Managed Postgres + EKS/ECS, enterprise compliance | [DEPLOY-AWS.md](./DEPLOY-AWS.md) |

## What you're deploying

The Phase 4 stack consists of:

- **wake-api** — FastAPI HTTP + SSE endpoint (stateless, horizontally scalable).
- **wake-worker** — Harness execution tier; consumes sessions via Postgres advisory
  locks; scale by replica count. Multi-worker is correct by construction.
- **Postgres 16** — Authoritative event store. Partitioned events table + advisory
  locks + LISTEN/NOTIFY.
- **Redis** — Pub/sub fan-out for SSE clients + lightweight job hints.
- **agentgateway** — Egress proxy (Rust). Filters outbound traffic by allowed_hosts,
  routes MCP HTTP, injects vault credentials.
- **Infisical Agent Vault** — Credential storage. Production replacement for the
  hardcoded env-var pattern Phase 1 used.

## Decision matrix

| Question | Answer | Path |
|----------|--------|------|
| Do you have a Kubernetes cluster? | Yes | Helm chart |
| Single host, < 100 sessions, want minimum ops? | Yes | Docker Compose |
| Want managed Postgres + zero infra? | Yes | Fly.io with Fly Postgres |
| Enterprise / VPC / compliance? | Yes | AWS EKS + RDS |

## Configuration surface

All deploy targets share the same config surface, expressed as env vars
or Helm values:

| Setting | Env var | Helm value |
|---------|---------|-----------|
| Postgres DSN | `WAKE_DATABASE_URL` | `postgres.*` |
| Redis URL | `WAKE_REDIS_URL` | `redis.*` |
| Vault URL | `WAKE_VAULT_URL` | `vault.url` |
| agentgateway URL | `WAKE_AGENTGATEWAY_URL` | `agentgateway.*` |
| Anthropic API key | `ANTHROPIC_API_KEY` | `secrets.anthropicApiKey` |
| OpenAI API key | `OPENAI_API_KEY` | `secrets.openaiApiKey` |
| Log level | `WAKE_LOG_LEVEL` | (env override) |
| OTLP endpoint | `OTEL_EXPORTER_OTLP_ENDPOINT` | `observability.otel.endpoint` |

## Networking model

```
                ┌─────────────┐
                │   client    │
                └─────┬───────┘
                      │  HTTPS / SSE
                      ▼
              ┌───────────────┐
              │   wake-api    │  (stateless, N replicas)
              └─────┬─────────┘
                    │ SQL + LISTEN/NOTIFY
                    │ Redis pub/sub
                    ▼
   ┌────────────┐   ┌────────────┐    ┌────────────┐
   │ wake-worker│ ◄─┤  postgres  ├──▶ │ wake-worker│ … (M replicas)
   └─────┬──────┘   └────────────┘    └─────┬──────┘
         │                                  │
         └────────── egress ─────┬──────────┘
                                 │
                         ┌───────▼──────────┐
                         │  agentgateway    │  (sidecar)
                         └──────┬───────────┘
                                │
                                ▼
                ┌─────────────────────────────┐
                │  external APIs / MCP servers│
                └─────────────────────────────┘

                ┌──────────────────┐
                │ infisical-vault  │  ◄── agentgateway pulls per-route creds
                └──────────────────┘
```

## Sizing guidance

| Sessions concurrent | API replicas | Worker replicas | Postgres tier | Redis |
|---------------------|--------------|-----------------|---------------|-------|
| < 10 | 1 | 1 | t3.small / shared | shared |
| 10–100 | 2 | 2–3 | db.t3.medium | small |
| 100–1000 | 3–4 | 5–10 | db.r6.large (replica) | dedicated |
| > 1000 | 6+ | 20+ | dedicated cluster | clustered |

## Backup & DR

- Postgres: enable WAL archiving (`wal-g` or managed service backups).
  RPO target ≤ 5 min, RTO ≤ 30 min for Phase 4.
- Vault: Infisical replicates its keys to Postgres; same backup covers both.
- Compose / Helm both store state only in Postgres + Vault — workers and
  API are entirely ephemeral.

## Upgrading

The chart's `appVersion` tracks the Wake API image tag. To upgrade
in-place:

```bash
helm upgrade wake ./deploy/helm/wake --set image.tag=0.4.1
```

Workers are stateless; rolling restart is safe.
