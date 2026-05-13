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

### Bootstrap env vars (Phase 5.1)

`wake server` and `wake worker` share a single production factory
(`wake.api.bootstrap.create_production_app` / `build_components`). It
reads the following env vars at startup:

| Variable | Default | Meaning |
|----------|---------|---------|
| `WAKE_DATABASE_URL` | `sqlite+aiosqlite:///./wake.db` | SQLAlchemy DSN. A `postgres*` prefix triggers the optional `wake-store-postgres` adapter — install via `pip install wake-store-postgres`. |
| `WAKE_SANDBOX_BACKEND` | `docker` | One of `docker`, `sandbox-runtime`, or `none`. `none` disables tool execution (catalog / replay only). |
| `WAKE_VAULT_PROVIDER` | `none` | `infisical` wires the Infisical adapter when installed; anything else falls back to the entry-point registry. |
| `WAKE_API_KEY` | _(unset)_ | Forwarded to the auth dependency. Required in production deployments. |
| `WAKE_API_CORS_ORIGINS` | dashboard dev origin | Comma-separated allowlist. |
| `WAKE_WORKER_POLL_INTERVAL_S` | `1.0` | Seconds the worker waits between store polls when idle. |
| `WAKE_PG_HEARTBEAT_INTERVAL_S` | `10` | Heartbeat cadence for Postgres-backed workers. |

### Running the components

```bash
# Server (uvicorn via --factory)
wake server                       # 0.0.0.0:8080, reads env vars above

# Worker — same env surface, plus advisory locks against Postgres
wake worker --concurrency 4       # 4 in-flight sessions per replica
```

`wake worker` exits gracefully on `SIGTERM` / `SIGINT`: the loop stops
scheduling new sessions and waits for in-flight steps to drain (bounded
to 30 s).

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
