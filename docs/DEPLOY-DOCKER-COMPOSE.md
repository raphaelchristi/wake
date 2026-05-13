# Deploy: Docker Compose (single host)

Self-hosted, single-machine deployment. Best for self-evaluations,
internal POCs, and dev environments that need the full Phase 4
topology.

## Prerequisites

- Docker Engine ≥ 24 / Docker Desktop ≥ 4.30
- 4 GB RAM minimum (8 GB recommended)
- Outbound HTTPS to Anthropic/OpenAI/etc.

## 1. Configure secrets

Create `.env` next to the compose file:

```bash
cd deploy
cat > .env <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
INFISICAL_ENCRYPTION_KEY=$(openssl rand -hex 16)
INFISICAL_AUTH_SECRET=$(openssl rand -base64 32)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
WAKE_LOG_LEVEL=info
EOF
chmod 600 .env
```

## 2. Bring up the stack

```bash
docker compose up -d
docker compose ps
```

The first start pulls images (~1–2 GB total) and initialises Postgres
+ Infisical. Health checks gate `wake-api` / `wake-worker` until the
data tier is ready.

Validate:

```bash
curl http://localhost:8080/health
```

## 3. Scale workers

The harness tier scales by replica count. Each worker claims sessions
via Postgres advisory locks, so adding workers is correct without
explicit sharding.

```bash
docker compose up -d --scale wake-worker=4
```

## 4. Configure agentgateway egress

By default `deploy/agentgateway/config.yaml` whitelists the major LLM
+ MCP endpoints. To add another upstream:

```yaml
allowed_hosts:
  - api.anthropic.com
  - api.openai.com
  - api.github.com
  - your.custom.api
mcp_routes:
  - name: custom
    upstream: https://your.custom.api
    auth:
      type: bearer
      vault_ref: custom_token
```

Reload by restarting the gateway container:

```bash
docker compose restart agentgateway
```

## 5. Seed the vault

Once Infisical is up at `http://localhost:8200` complete the web setup
wizard (admin user + project) and capture an API token. Then:

```bash
export INFISICAL_TOKEN=...
wake vault add github_token --provider github --oauth \
  --client-id $GITHUB_OAUTH_CLIENT_ID \
  --client-secret $GITHUB_OAUTH_CLIENT_SECRET
```

(Or, for a quick dev run, `wake vault add github_token --provider github --value ghp_xxx`.)

## 6. Dev mode (hot reload)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The overlay mounts `src/` and `adapters/` into both containers and
turns on `uvicorn --reload`. Code edits hot-reload without rebuilding.

## 7. Logs & troubleshooting

```bash
docker compose logs -f wake-api wake-worker
docker compose logs --tail=200 agentgateway infisical-vault
```

Common issues:

| Symptom | Fix |
|--------|-----|
| `wake-api` restart loop, no DB connection | Wait for Postgres health to flip green; check `POSTGRES_PASSWORD` matches across services |
| `agentgateway` 403 on every request | Host missing from `allowed_hosts` — edit the config + restart |
| Vault auth errors | Re-roll `INFISICAL_AUTH_SECRET`; recreate vault user via web UI |

## 8. Backups

The compose stack persists Postgres data in the `pgdata` named volume.
Snapshot it with `docker run --rm -v wake_pgdata:/from -v $PWD:/to alpine
tar -czf /to/pgdata.tgz -C /from .`. For continuous backups, point
`wal-g` at a Postgres replica.

## 9. Tear down

```bash
docker compose down              # keep volumes
docker compose down -v           # nuke volumes (lose data)
```

## What this gives you

- ✅ Multi-worker harness with crash-recovery (kill any worker, see `examples/05-kill-and-resume`)
- ✅ Vault-backed credential lifecycle
- ✅ Egress-filtered MCP routing
- ✅ Cost tracking via LiteLLM callbacks
- ❌ Multi-host HA (use Helm for that)
- ❌ Zero-downtime upgrades (compose restarts kill in-flight steps)

For anything beyond single-host, follow [DEPLOY-KUBERNETES.md](./DEPLOY-KUBERNETES.md).
