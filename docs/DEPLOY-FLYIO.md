# Deploy: Fly.io

Fast, opinionated managed deploy. Fly takes the same Dockerfile and
runs it across regions. Pair with **Fly Postgres** for a complete
managed stack.

## Prerequisites

- `flyctl` ≥ 0.2
- A Fly account + payment method (Postgres requires it even on free tier)
- The Wake repository checked out locally

## 1. Bootstrap

```bash
flyctl auth login
flyctl launch --no-deploy --copy-config --name wake-api \
  --dockerfile deploy/Dockerfile
```

Edit the generated `fly.toml`:

```toml
app = "wake-api"
primary_region = "gru"   # São Paulo; pick yours

[build]
  dockerfile = "deploy/Dockerfile"

[[services]]
  internal_port = 8080
  protocol = "tcp"
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [[services.ports]]
    port = 80
    handlers = ["http"]
    force_https = true

  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [[services.tcp_checks]]
    interval = "15s"
    timeout = "2s"

[env]
  WAKE_LOG_LEVEL = "info"
```

## 2. Managed Postgres

```bash
flyctl postgres create --name wake-pg --region gru --vm-size shared-cpu-1x --initial-cluster-size 1
flyctl postgres attach --app wake-api wake-pg
```

`attach` injects `DATABASE_URL` into the Wake app secrets. We re-export
as `WAKE_DATABASE_URL` in a release command:

```toml
[deploy]
  release_command = "wake migrate"     # runs alembic upgrade head
```

And:

```bash
flyctl secrets set --app wake-api \
  WAKE_DATABASE_URL="$(flyctl ssh console -a wake-api -C 'printenv DATABASE_URL' | sed 's/postgres:/postgresql+asyncpg:/')"
```

## 3. Vault

Run a second Fly app for Infisical, or use the Fly Volumes + the
Infisical image:

```bash
flyctl launch --no-deploy --image infisical/infisical:latest --name wake-vault
flyctl secrets set --app wake-vault \
  ENCRYPTION_KEY=$(openssl rand -hex 16) \
  AUTH_SECRET=$(openssl rand -base64 32)
```

Point the API at it:

```bash
flyctl secrets set --app wake-api WAKE_VAULT_URL=http://wake-vault.internal:8080
```

## 4. agentgateway

The bundled `agentgateway` Rust binary runs as a Fly app too. Build a
small image around `ghcr.io/agentgateway/agentgateway:latest` that
copies in `deploy/agentgateway/config.yaml`.

```dockerfile
FROM ghcr.io/agentgateway/agentgateway:latest
COPY deploy/agentgateway/config.yaml /etc/agentgateway/config.yaml
EXPOSE 8888
CMD ["--config", "/etc/agentgateway/config.yaml"]
```

```bash
flyctl launch --name wake-gw --dockerfile Dockerfile.gw --no-deploy
flyctl secrets set --app wake-api WAKE_AGENTGATEWAY_URL=http://wake-gw.internal:8888
```

## 5. Worker tier

Fly runs workers as a separate "process group" in the same app:

```toml
[processes]
  api = "wake server --host 0.0.0.0 --port 8080"
  worker = "wake worker --concurrency 4"
```

```bash
flyctl deploy
flyctl scale count worker=3 --app wake-api
```

## 6. LLM keys

```bash
flyctl secrets set --app wake-api \
  ANTHROPIC_API_KEY=sk-ant-... \
  OPENAI_API_KEY=sk-...
```

## 7. Regions / scaling

```bash
flyctl regions add gru iad fra --app wake-api
flyctl scale count api=2 worker=4 --app wake-api
```

Workers in different regions all talk to the same Postgres; advisory
locks coordinate session ownership.

## 8. Logs & metrics

```bash
flyctl logs --app wake-api
flyctl status --app wake-api
```

Fly exposes Prometheus metrics at `:9091/metrics` per machine; scrape
from Grafana Cloud or whatever you use.

## Trade-offs

| Pros | Cons |
|------|------|
| One-command global deploys | No Helm primitives — each component is its own app |
| Managed Postgres | Vault + agentgateway need their own apps |
| Free tier covers POCs | Fly Postgres single-node by default; HA costs extra |
