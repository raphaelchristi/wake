# Wake Dashboard — operator guide

> The Wake Dashboard is a Next.js 15 SPA that lets you observe and operate
> a running Wake deployment: list sessions, replay event streams, watch
> live latency / cost / throughput metrics, and manage OAuth credentials
> stored in the vault. This document is the **operator** reference. If
> you are looking for the architecture rationale, see
> [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) and the slice contract
> [`phases/PHASE-5-CONTRACT.md`](../phases/PHASE-5-CONTRACT.md).

## Table of contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Local development](#local-development)
- [Authentication](#authentication)
- [Customization & branding](#customization--branding)
- [Deploying with Docker Compose](#deploying-with-docker-compose)
- [Deploying on Kubernetes with Helm](#deploying-on-kubernetes-with-helm)
- [Environment variables](#environment-variables)
- [Operational endpoints](#operational-endpoints)
- [Vault integration](#vault-integration)
- [Metrics surface](#metrics-surface)
- [OAuth flow walkthrough](#oauth-flow-walkthrough)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Appendix: API reference](#appendix-api-reference)

---

## Overview

Wake ships with a self-hostable operator UI. The dashboard talks to the
Wake API (FastAPI, served by `wake-api`) using a single bearer-style
header (`X-Wake-API-Key`) and renders three primary surfaces:

| Surface | Path | What it shows |
|---|---|---|
| Sessions | `/sessions` | Paginated table of every Wake session, with filter by agent / status / model / time / free-text. Click a row to open the detail view. |
| Replay | `/sessions/{id}/replay` | Scrubber + event timeline + reconstructed sandbox state for any past session. |
| Metrics | `/metrics` | Latency p50/p95/p99, USD cost, sessions/h throughput, error rate, worker liveness, queue depth. Auto-refresh every 30s. |
| Vault | `/vault` and `/vault/audit` | List of credentials stored in the vault (metadata only — never tokens), add/rotate/revoke flows, full audit log of every vault access. |

The dashboard is **stateless** — every page loads its data from the
Wake API on render. There is no separate dashboard database; the
Wake API is the single source of truth.

### Architecture summary

```
+--------------------+        +---------------------+        +--------------+
|  browser (Next.js) | -----> |  wake-dashboard     | -----> |  wake-api    |
|  React 19 / RSC    |  HTTP  |  Next.js standalone |  HTTP  |  FastAPI     |
+--------------------+        +---------------------+        +--------------+
                                                                  |
                                                                  v
                                                       +---------------------+
                                                       |  postgres / redis   |
                                                       |  vault (Infisical)  |
                                                       |  agentgateway       |
                                                       +---------------------+
```

The Next.js container is a thin shell: it owns the OAuth callback
relay (`/oauth/callback/api`) and a couple of metadata-only endpoints,
but never talks to Postgres / Redis directly.

---

## Screenshots

> Placeholders. Replace with real captures after `pnpm dev` is running
> against your environment. See [`docs/assets/`](./assets/) for the
> existing brand banner if you want a consistent backdrop.

| Surface | File | Recommended size |
|---|---|---|
| Sessions list | `docs/assets/dashboard-sessions.png` | 1600×900 |
| Replay scrubber | `docs/assets/dashboard-replay.png` | 1600×900 |
| Metrics overview | `docs/assets/dashboard-metrics.png` | 1600×900 |
| Vault list | `docs/assets/dashboard-vault.png` | 1600×900 |
| Audit log | `docs/assets/dashboard-vault-audit.png` | 1600×900 |

Until these exist, the dashboard renders fine; the docs simply lack
visual examples.

---

## Local development

### Prerequisites

- Node **22.13+** (Next 15 requirement). On macOS:
  `fnm install 22 && fnm use 22`.
- pnpm 9 — `corepack enable && corepack prepare pnpm@9.15.9 --activate`.
- Python 3.11+ with `uv` or `pip` to run the backend.
- Optional but recommended: Postgres 16 + Redis 7 (Docker is fine).

### Step 1 — start the backend

```bash
# in repo root
python -m venv .venv && source .venv/bin/activate
pip install -e .

# minimum env — pick a different db if you want multi-process
export WAKE_API_KEY="dev-key-please-change"
export WAKE_DATABASE_URL="sqlite+aiosqlite:///wake.db"
export WAKE_LOG_LEVEL="debug"

uvicorn wake.api.app:app --host 0.0.0.0 --port 8080 --reload
```

You should see `INFO:     Application startup complete.` and
`curl http://localhost:8080/health` should return `{"ok": true}`.

### Step 2 — start the dashboard

```bash
cd frontend
pnpm install
NEXT_PUBLIC_WAKE_API_BASE="http://localhost:8080" pnpm dev
```

The dev server prints `Local: http://localhost:3000` and opens with a
login form. Paste the same `WAKE_API_KEY` value into the input and you
are in.

### Step 3 — generate some data

The dashboard is more useful when there's something to look at:

```bash
# Create a session via the API directly (replace key)
curl -s -X POST http://localhost:8080/sessions \
  -H "Content-Type: application/json" \
  -H "X-Wake-API-Key: dev-key-please-change" \
  -d '{"agent_id": "default", "model": "claude-3-5-haiku-latest"}'
```

After a few `user.message` / `assistant.message` events, `/metrics`
will start showing real numbers and `/vault/audit` will record any
vault accesses.

### Common dev scripts

```bash
# inside frontend/
pnpm dev              # next dev server
pnpm build            # production build (standalone)
pnpm start            # serve the standalone build
pnpm lint             # next lint
pnpm typecheck        # tsc --noEmit
pnpm test             # vitest run
pnpm test:watch       # vitest --watch
pnpm test:e2e         # playwright test (needs `pnpm dev` running)
pnpm format           # prettier --write .
```

---

## Authentication

The dashboard authenticates against the backend with an **API key** that
travels in the `X-Wake-API-Key` header. Data access is scoped by
`X-Wake-Organization-Id` and `X-Wake-Workspace-Id`; when those headers
are absent Wake falls back to `default/default` for local and
single-tenant deployments. Product teams should inject the tenant
headers from their own auth layer or reverse proxy.

### Generating an API key

The Wake backend reads its API key from the `WAKE_API_KEY` env var. Any
long random string works:

```bash
export WAKE_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

You can rotate the key at any time by restarting the API with a new
value — the browser will get a 401 on the next request and bounce the
user to `/login`.

### Where the key lives in the browser

The `dashboard-shell` slice persists the key in `localStorage` under the
key `wake.api_key`. Never check this value into source control. The
key is **not** stored in a cookie — that's intentional to avoid CSRF
on multi-tenant deployments. If you want to put the dashboard behind
SSO (e.g. via Cloudflare Access or an OAuth2 proxy) we recommend
delegating auth to the reverse proxy and configuring the dashboard's
Next.js layer with `WAKE_API_KEY` server-side (see
[`Environment variables`](#environment-variables)).

### Server-side fallback (optional)

For deployments where the operator does not want to expose the key to
the browser at all, the dashboard supports a server-side relay for the
OAuth callback path. Set `WAKE_API_KEY` on the **Next.js process**
and the `/oauth/callback/api` route will inject it on every upstream
call. The browser only ever sees the credential metadata that comes
back from the backend.

---

## Customization & branding

The frontend uses Tailwind v4 + shadcn/ui primitives. All theming
flows through CSS variables defined in `frontend/src/app/globals.css`
(owned by the `dashboard-shell` slice):

```css
:root {
  --background: 0 0% 100%;
  --foreground: 220 13% 18%;
  --primary: 217 91% 60%;
  --primary-foreground: 0 0% 98%;
  --muted: 220 14% 96%;
  /* ...etc */
}
.dark {
  --background: 220 13% 9%;
  --foreground: 0 0% 98%;
  /* ...etc */
}
```

To re-brand:

1. Override CSS variables in `globals.css` (or a follow-on stylesheet
   imported after it).
2. Replace the logo asset in `frontend/public/logo.svg` (shell slice).
3. Optionally set `NEXT_PUBLIC_WAKE_BRAND_NAME="Acme Wake"` — the topbar
   reads this env var.

The chart colours in `frontend/src/components/metrics/*Chart.tsx` are
deliberately hard-coded brand-neutral hues (indigo, amber, red, green,
blue) so they read in any theme. If you want them token-driven, swap
the literal hex codes for `hsl(var(--chart-1))` etc. and define the
variables in `globals.css`.

---

## Deploying with Docker Compose

The repository ships a single-host topology in
[`deploy/docker-compose.yml`](../deploy/docker-compose.yml). It
brings up six services:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | Event store + advisory locks |
| `redis` | `redis:7-alpine` | 6379 | Pub/sub fan-out |
| `agentgateway` | `ghcr.io/agentgateway/agentgateway:latest` | 8888 | Egress proxy / MCP routing |
| `infisical-vault` | `infisical/infisical:latest` | 8200 | Credential vault |
| `wake-api` | built from `deploy/Dockerfile` | 8080 | FastAPI backend |
| `wake-worker` | same image, different cmd | — | Harness worker pool |
| `wake-dashboard` | built from `deploy/Dockerfile.frontend` | 3000 | Next.js standalone |

### Bring it up

```bash
cp .env.example .env  # populate POSTGRES_PASSWORD, INFISICAL_* keys, OAuth keys

# Required: shared API key for dashboard ↔ backend. Compose fails
# fast if you forget to export it.
export WAKE_API_KEY="$(openssl rand -hex 32)"

docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps
```

Check health:

```bash
curl http://localhost:8080/health
curl -I http://localhost:3000
```

### Scale workers

```bash
docker compose -f deploy/docker-compose.yml up -d --scale wake-worker=3
```

Postgres advisory locks keep dispatch fair across workers; you should
see all three workers appear in `/metrics` under the worker grid within
~30s.

### Dev override

For hot-reload during dev, include `deploy/docker-compose.dev.yml` as a
second `-f` argument. It mounts source volumes and switches the API
command to `uvicorn --reload`.

### Tearing it down

```bash
docker compose -f deploy/docker-compose.yml down -v   # -v drops Postgres data
```

---

## Deploying on Kubernetes with Helm

A turnkey Helm chart lives in [`deploy/helm/wake/`](../deploy/helm/wake/).
It is intentionally minimal — three Deployments (api, worker,
dashboard), one StatefulSet (Postgres), services, an Ingress, and a
single configmap + secret pair.

### Install

```bash
# Generate a strong key once and reuse it for every install.
export WAKE_API_KEY="$(openssl rand -hex 32)"

helm install wake deploy/helm/wake \
  --namespace wake --create-namespace \
  --set auth.apiKey="$WAKE_API_KEY" \
  --set frontend.image.repository=wake-ai/dashboard \
  --set frontend.image.tag=0.5.0 \
  --set frontend.publicApiUrl=https://wake.example.com
```

For production, reference an existing Secret instead of passing the
key on the CLI:

```bash
kubectl -n wake create secret generic wake-api-key-secret \
  --from-literal=key="$(openssl rand -hex 32)"

helm install wake deploy/helm/wake \
  --namespace wake \
  --set auth.apiKeySecretRef.name=wake-api-key-secret \
  --set auth.apiKeySecretRef.key=key
```

The chart refuses to install when `auth.required=true` (the default)
and neither `auth.apiKey` nor `auth.apiKeySecretRef.name` is set —
this surfaces a missing API key as a clear install error instead of
shipping a fail-open API. Set `auth.required=false` only for fully
internal dev clusters where you understand the risk.

### Lint before you ship

```bash
helm lint deploy/helm/wake
helm template wake deploy/helm/wake --set apiKey=dummy
```

Both should run clean. CI runs `helm lint` on every PR.

### Ingress routing

The Ingress in `deploy/helm/wake/templates/ingress.yaml` routes:

- `/api/*` → `wake-api` service on port 8080
- everything else → `wake-frontend` service on port 3000

This keeps `same-origin` invariants happy in the browser — the
dashboard simply calls `/api/sessions` from its own host. If you
prefer a separate host (`api.wake.example.com` and
`wake.example.com`), set `frontend.apiHost=https://api.wake.example.com`
in the values; the Next.js process then injects
`NEXT_PUBLIC_WAKE_API_BASE` at build time.

### Frontend image

The dashboard image is built by `deploy/Dockerfile.frontend`. It is a
classic multi-stage Next.js build:

1. `node:22-alpine` with pnpm — installs deps
2. `pnpm build` → `.next/standalone`
3. Final `node:22-alpine` runs `node server.js` on port 3000

The image runs as a non-root user (`uid 1001`) and ships with an empty
healthcheck (`GET /` returns 200 once warm). Resource requests in
`values.yaml` default to 100m CPU / 128Mi memory — bump for HA.

### Replicas + HPA

```yaml
frontend:
  replicas: 2
  hpa:
    enabled: true
    minReplicas: 2
    maxReplicas: 6
    targetCPUUtilizationPercentage: 70
```

The dashboard is stateless so horizontal scaling is trivial. If you
turn the HPA on, make sure your Ingress sticky-sessions are **off** —
there is no per-pod state to be sticky to.

---

## Environment variables

### Backend (`wake-api`, `wake-worker`)

| Variable | Default | Description |
|---|---|---|
| `WAKE_API_KEY` | — | Shared API key for dashboard auth. **Required in production.** |
| `WAKE_AUTH_REQUIRED` | `false` | Fail-closed flag. When `true`, every authenticated route returns 503 unless `WAKE_API_KEY` is also set — guards against deploy manifests that forget to inject the Secret. Helm + Compose default to `true`. |
| `WAKE_DATABASE_URL` | `sqlite+aiosqlite:///wake.db` | SQLAlchemy URL. Use `postgresql+asyncpg://...` for prod. |
| `WAKE_REDIS_URL` | `redis://localhost:6379` | Used for pub/sub fan-out + queue. |
| `WAKE_VAULT_URL` | unset | If set, enables the Infisical vault adapter. Vault routes return 503 when unset. |
| `WAKE_VAULT_TOKEN` | unset | Auth token for the vault adapter. |
| `WAKE_AGENTGATEWAY_URL` | unset | Egress proxy URL. Without this all tool calls go direct. |
| `WAKE_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error`. |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic adapters. |
| `OPENAI_API_KEY` | — | Required for OpenAI adapters. |
| `WAKE_OAUTH_<PROVIDER>_CLIENT_ID` | — | OAuth client ID for `github` / `slack` / `notion`. |
| `WAKE_OAUTH_<PROVIDER>_CLIENT_SECRET` | — | OAuth client secret. |
| `WAKE_OAUTH_<PROVIDER>_REDIRECT_URI` | `http://localhost:3000/oauth/callback` | Override per env. |

#### Auth modes (canonical truth table)

| `WAKE_API_KEY` | `WAKE_AUTH_REQUIRED` | Behaviour |
|---|---|---|
| unset | unset / false | **No-op** — accepts every request. Dev only. |
| set   | any           | Header `X-Wake-API-Key` must equal the value. |
| unset | `true`        | **Fail-closed** — every auth'd route returns 503 "auth required but not configured". |

`/health`, `/docs`, `/redoc`, `/openapi.json` are unauthenticated in
every mode.

### Frontend (`wake-dashboard`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_WAKE_API_BASE` | `http://localhost:8080` | URL the **browser** uses to reach the API. Public, baked into the client bundle at build time. |
| `WAKE_API_URL` | unset (falls back to `NEXT_PUBLIC_WAKE_API_BASE`) | URL the **Next.js server process** uses to reach the API (OAuth callback proxy). Private, never exposed to the browser. Set to the in-cluster Service URL in production. |
| `WAKE_API_KEY` | unset | Server-side API key used by `/oauth/callback/api` to inject `X-Wake-API-Key`. Browser never sees it. |
| `NEXT_PUBLIC_WAKE_BRAND_NAME` | `Wake` | Brand name shown in the topbar. |
| `PLAYWRIGHT_BASE_URL` | `http://localhost:3000` | Override for e2e tests against a non-default port. |

All `NEXT_PUBLIC_*` variables are **baked into the bundle at build
time**; the others are read at runtime by the Node server.

> **Deprecated:** `NEXT_PUBLIC_API_URL` (pre-Phase-5.1 alias). The
> client still falls back to it with a `console.warn` for one
> transition release; remove from your deploy manifests and use
> `NEXT_PUBLIC_WAKE_API_BASE` going forward.

---

## Operational endpoints

The dashboard relies on these backend endpoints. Treat the column order
as load-bearing — the table is reused in the OpenAPI spec.

| Method | Path | Used by | Notes |
|---|---|---|---|
| `GET` | `/health` | dashboard ping + k8s probe | returns `{"ok": true}` |
| `GET` | `/sessions` | `/sessions` page | accepts filter query params (agent/status/model/since/until/q/page/page_size) |
| `GET` | `/sessions/{id}` | session detail | returns the full Session |
| `GET` | `/sessions/{id}/events` | replay page | returns the full event array |
| `GET` | `/sessions/{id}/stream` | replay page (live) | SSE; emits new events as they happen |
| `GET` | `/sessions/{id}/state-at/{seq}` | replay scrubber | reconstructs sandbox state at a given seq |
| `GET` | `/v1/metrics/summary?window=1h\|24h\|7d\|30d` | `/metrics` | aggregated stats + time-series |
| `GET` | `/v1/workers` | `/metrics` | worker heartbeat list |
| `GET` | `/v1/vault/credentials` | `/vault` | metadata only — no tokens |
| `POST` | `/v1/vault/oauth/start` | Add credential dialog | returns `{auth_url, state}` |
| `GET` | `/v1/vault/oauth/callback?code=&state=` | callback page | exchanges code for token, stores in vault |
| `POST` | `/v1/vault/credentials/{id}/rotate` | Rotate dialog | starts a new OAuth for same provider/scopes |
| `DELETE` | `/v1/vault/credentials/{id}` | revoke | idempotent |
| `GET` | `/v1/vault/audit?...` | `/vault/audit` | filters by provider/host/decision/since/limit |

All `/v1/vault/*` endpoints return **503 Vault not configured** when no
vault adapter is wired. The dashboard interprets this as the
`offline` state — it shows a friendly card rather than a generic error.

---

## Vault integration

### How it works

Wake's vault is a thin abstraction over `wake_vault_infisical`. The
adapter implements three methods:

- `list() -> Sequence[CredentialMetadata]` — for the dashboard list
- `add(name, provider, value, scopes, metadata) -> CredentialMetadata`
- `revoke(vault_id) -> None` (idempotent)

The dashboard **never** sees the `value`. The backend's
`/vault/credentials` route filters out the `access_token` field before
returning the metadata.

### Configuring providers

For each provider you want to use (GitHub, Slack, Notion), register an
OAuth app on the provider's side and set the matching env vars:

```bash
# GitHub example
export WAKE_OAUTH_GITHUB_CLIENT_ID="Iv1.abcdef"
export WAKE_OAUTH_GITHUB_CLIENT_SECRET="..."
export WAKE_OAUTH_GITHUB_REDIRECT_URI="https://wake.example.com/oauth/callback"
```

In the provider's settings page, list the redirect URI you used above.
For local dev, `http://localhost:3000/oauth/callback` works fine.

### Audit log retention

The audit log is **in-memory**, scoped to the FastAPI process. That is
intentional for v0.5 — most operators want a quick "what just
happened?" view. If you need durable audit, point Wake at a Postgres
that has the `wake_vault_audit` migration applied (see
[`docs/SPEC-EVENT-SCHEMA.md`](./SPEC-EVENT-SCHEMA.md) appendix); the
backend will persist there automatically.

### Revoking on the provider side

`DELETE /v1/vault/credentials/{id}` removes the credential from Wake's
vault. It does **not** revoke the token at the upstream provider — for
GitHub you'd hit `POST /applications/{client_id}/grant`, for Slack
`auth.revoke`. We deliberately keep this manual because the right
revocation semantics are different per provider.

---

## Metrics surface

### What is aggregated

- **Latency**: wall-clock between `user.message` and the **last**
  `assistant.message` in the same session. Plotted as p50/p95/p99
  per bucket. Cold sessions (no assistant reply yet) are excluded.
- **Cost**: sum of `payload.cost_usd` and `metadata.cost_usd` across
  `assistant.message` and `tool_result` events. LiteLLM populates
  these fields on the callback hook.
- **Throughput**: count of distinct sessions started inside the
  window. We **do not** divide by 24h naively — we divide by the
  window length so 1h windows show a true per-hour rate.
- **Error rate**: fraction of sessions that emitted ≥1 `error` event.

### Buckets

The bucket size is chosen by the backend to keep the chart readable:

| Window | Bucket | Points |
|---|---|---|
| 1h | 1 min | ~60 |
| 24h | 30 min | ~48 |
| 7d | 4h | ~42 |
| 30d | 1d | ~30 |

### Workers + queue

- A **worker** is identified by `meta._heartbeat.worker` (Postgres
  store only). SQLite single-process deployments synthesize a `local`
  worker entry when at least one session is running.
- The **queue depth** is the count of sessions in `idle` status — i.e.
  not yet picked up by a worker. A growing queue depth is the canonical
  "scale up workers" signal.

### Auto-refresh

- `/v1/metrics/summary` polls every **30s**
- `/v1/workers` polls every **15s** (worker heartbeats churn faster)
- Manual Refresh button forces both immediately

When `/v1/metrics/summary` fails the dashboard **keeps the previous
values** and renders an inline error card — operators stay oriented
even during transient backend outages.

---

## OAuth flow walkthrough

End-to-end trace of "Add GitHub credential":

1. Operator clicks **Add credential** on `/vault`. The dialog opens
   with provider=`github`, default scopes `repo,read:user`.
2. Operator submits. The dashboard POSTs to
   `/v1/vault/oauth/start` with `{provider, scopes, redirect_uri}`.
3. Backend constructs a GitHub authorize URL with a random `state`
   (CSRF). It stashes the in-flight flow in `state.oauth_flows[state]`
   and returns `{auth_url, state}`.
4. Dashboard stashes `{provider, auth_url}` in `sessionStorage` under
   `wake.oauth.<state>` so the callback page can show context, then
   redirects the browser to `auth_url`.
5. Operator authorizes on GitHub. Provider redirects to
   `redirect_uri?code=...&state=...`.
6. The Next.js `/oauth/callback` page loads, picks up `code` and
   `state` from the URL, and POSTs them to `/oauth/callback/api`.
7. The Next route handler forwards a GET to
   `/v1/vault/oauth/callback?code=&state=` on the backend (optionally
   injecting `X-Wake-API-Key` from `WAKE_API_KEY` env var).
8. Backend exchanges the code for an access token via the
   `OAuthFlow.for_provider("github")` helper, then writes the token
   into the vault via `vault.add(...)`. Returns the credential
   metadata (no token).
9. The callback page renders "Credential stored" with provider, name,
   and vault ID; it clears the sessionStorage entry.

Failure modes are handled at every step:

- **Step 2** — backend returns 400 if the provider is unknown, 500 if
  the OAuth client isn't configured. Dialog surfaces the message inline.
- **Step 5** — provider may redirect with `?error=access_denied`. The
  callback page reads `error` + `error_description` and shows them.
- **Step 7-8** — any backend non-2xx (404 unknown state, 502 vault
  error) is propagated as JSON `{error}` and rendered on the callback
  page with a `ShieldAlert` icon.

---

## Troubleshooting

### Q: The dashboard is stuck at `Loading…` and nothing else happens

Open browser devtools → Network tab → look for `/sessions` or
`/v1/metrics/summary` requests. Common causes:

- **CORS preflight failing**: the backend allows `*` by default but
  some reverse proxies strip the `Access-Control-Allow-Origin` header.
  Add an explicit `add_header` rule in nginx or set
  `WAKE_CORS_ORIGINS="https://wake.example.com"` on the backend.
- **Wrong `NEXT_PUBLIC_WAKE_API_BASE`**: the bundle was built pointing
  at a different host. Rebuild with the right value or use the
  same-origin pattern via the Helm Ingress.
- **Network blocking**: corporate firewall stripping the
  `X-Wake-API-Key` header. Curl directly to verify.

### Q: `/metrics` shows zeros everywhere

Either there's no data in the window (try `30d`) or the events lack
`cost_usd` metadata. The LiteLLM adapter writes cost into
`metadata.cost_usd` on `assistant.message` events — if you're using a
custom adapter you'll need to do the same. The latency / throughput
metrics work regardless of cost.

### Q: `/vault` always shows `Vault offline`

The backend has no `wake_vault_infisical` configured. Either:

- set `WAKE_VAULT_URL` + `WAKE_VAULT_TOKEN` env vars, or
- delete the vault feature flag (vault routes still 503 — that's
  expected; the dashboard will keep showing the offline state).

The vault adapter is **lazy**: starting the backend without
`wake-vault-infisical` installed just means vault routes 503. The rest
of Wake works.

### Q: OAuth callback says `unknown or expired state`

The CSRF state stored on the backend evaporated. Two common causes:

- The backend restarted between `oauth/start` and the callback
  (in-memory flow storage). Restart your `Add credential` flow.
- Multiple backend replicas without a shared in-memory store —
  request hit a different pod from the one that started the flow. Pin
  OAuth traffic via cookie-stick on the Ingress, or stand up a single
  replica during onboarding.

### Q: Workers show as `stale` even though they're running

`HEARTBEAT_TIMEOUT_S` is 30s in `wake.api.routes.metrics`. If your
worker heartbeat interval is longer than that, the dashboard will
flag them stale. Lower the heartbeat interval on the worker side or
extend the timeout (PR welcome).

### Q: How do I rotate the dashboard API key without downtime?

1. Generate the new key on the backend with `WAKE_API_KEY=new`
   and restart the API (rolling). Briefly both `old` and `new` are
   accepted if you set `WAKE_API_KEY_PREVIOUS=old` (optional).
2. Distribute the new key out-of-band to operators.
3. Operators paste the new key on `/login` — the dashboard updates
   `localStorage` and reloads.

### Q: I get a 401 immediately after login

`X-Wake-API-Key` header is being stripped or your key has trailing
whitespace. Look in devtools → Network → request headers; verify the
header is present and matches the backend env var exactly.

### Q: `pnpm build` fails with `Cannot find module 'next-env.d.ts'`

This file is generated on first run. Either:

- `pnpm dev` once (creates the file), or
- `pnpm exec next build` — it generates the file before tsc runs.

### Q: Recharts complains about `0×0 container`

Means the chart was mounted before its parent had a measurable size,
typically inside an `Element.contains` test in happy-dom. We polyfill
`ResizeObserver` and inject default `window.innerWidth` in
`tests/unit/setup.ts`. If you see the warning at runtime, wrap the
chart in a `min-height` block.

---

## FAQ

**Is the dashboard production-ready?**
For self-hosted deployments — yes. We use it in-house. It is API-key
authenticated, workspace-scoped, and assumes the backend is the authority
on all data. SSO is still expected to live at the reverse-proxy or
product gateway layer.

**Why Next.js 15 instead of plain React + Vite?**
RSC + the App Router give us file-system routing, layouts, and a clean
boundary between the server-side OAuth proxy and the client app
without bringing in a separate API gateway.

**Can I run the dashboard against a remote Wake API?**
Yes. Set `NEXT_PUBLIC_WAKE_API_BASE=https://wake-api.example.com` at
build time and make sure CORS + the API key are configured. Same-origin
deployments (Ingress routes `/api/*` and `/*` to the same host) avoid
the CORS dance entirely.

**How do I add a new provider?**
Two places:
1. `src/wake/api/routes/vault.py` — add the provider name to
   `SUPPORTED_PROVIDERS`.
2. `frontend/src/components/vault/ProviderIcon.tsx` — add a glyph
   case for the new provider.
3. `frontend/src/components/vault/AddCredentialDialog.tsx` —
   add an entry to `PROVIDER_OPTIONS`.

The `wake_vault_infisical.OAuthFlow.for_provider(...)` factory has to
know how to build an authorize URL for your provider; if it doesn't,
extend that helper or pass a custom `OAuthFlow` instance.

**Does the dashboard work offline (no network)?**
No — it's an SPA that hits the API on every page. If you need an
air-gapped read-only view, export the sessions + events to JSON via
`wake events export` (CLI) and render them with a static viewer.

**How big can the events table get before the replay page chokes?**
We've tested 5k events in a single session. The replay scrubber
virtualizes the event list above 500. Beyond ~50k events per session
you'll want to chunk the replay client-side; that's open work.

**Why two folders in `app/(authed)/vault/` and `app/oauth/callback/`?**
The `(authed)` route group applies the auth gate via a shared layout.
The OAuth callback intentionally lives **outside** that group so the
provider's redirect doesn't bounce through the login form when the
session has expired during the round trip. The callback page can render
"please re-login" without nuking the in-flight OAuth state.

---

## Appendix: API reference

This section is a quick reference. The canonical reference is the
OpenAPI spec at `/openapi.json` on the running backend.

### `GET /v1/metrics/summary`

Query params:

- `window` — one of `1h`, `24h`, `7d`, `30d`. Default `24h`.

Response (shape excerpt):

```json
{
  "window": {
    "code": "24h",
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-02T00:00:00Z",
    "bucket_seconds": 1800
  },
  "latency": { "p50_ms": 200, "p95_ms": 800, "p99_ms": 1500, "samples": 42 },
  "cost": { "total_usd": 4.21, "avg_per_session_usd": 0.10, "max_session_usd": 0.55, "samples": 42 },
  "throughput": { "sessions": 42, "per_hour": 1.75 },
  "errors": { "count": 3, "rate": 0.07, "sessions_affected": 3 },
  "workers_alive": 2,
  "queue_depth": 1,
  "series": {
    "latency": [{ "t": "...", "p50": 200, "p95": 800, "p99": 1500 }],
    "cost":    [{ "t": "...", "cost_usd": 1.1 }],
    "throughput": [{ "t": "...", "sessions": 20 }],
    "errors":  [{ "t": "...", "errors": 1 }]
  }
}
```

### `GET /v1/workers`

No query params.

Response:

```json
{
  "data": [
    {
      "worker_id": "w-prod-1",
      "status": "alive",
      "last_heartbeat_at": "2025-01-01T00:00:00Z",
      "current_session_id": "s-abc",
      "current_sessions": ["s-abc"]
    }
  ]
}
```

Status is one of `alive` (heartbeat ≤ 30s ago, has running sessions),
`stale` (heartbeat > 30s ago), or `idle` (no current sessions).

### `GET /v1/vault/credentials`

No query params. Returns metadata only — `access_token` is filtered.

### `POST /v1/vault/oauth/start`

Body: `{ provider, scopes?, redirect_uri? }`. Returns
`{ provider, auth_url, state }`. The dashboard should redirect the
browser to `auth_url` and persist `state` in sessionStorage for the
callback page.

### `GET /v1/vault/oauth/callback?code=&state=`

Returns the same credential metadata shape as the list endpoint after
the code → token exchange and `vault.add(...)` call. Returns 400 if
`state` is unknown (already consumed or expired), 502 if the provider
exchange fails.

### `POST /v1/vault/credentials/{id}/rotate`

Body: `{ redirect_uri? }`. Returns the same shape as `/oauth/start`.
The dashboard treats this exactly like a new OAuth flow — the
backend correlates the new token to the existing credential when the
callback fires.

### `DELETE /v1/vault/credentials/{id}`

Idempotent — 204 even if `id` doesn't exist.

### `GET /v1/vault/audit`

Query params:

- `since` — ISO timestamp; only return entries after this.
- `limit` — int, 1..1000. Default 100.
- `provider` — exact match filter.
- `host` — exact match filter.
- `decision` — exact match filter.

Response: `{ data: AuditEntry[] }`. Each entry has `timestamp`,
`session_id`, `provider`, `host`, `decision`, `vault_id`, `detail`.

---

## Changelog (dashboard-specific)

### v0.5.0 (current — Phase 5)

- Initial Wake Dashboard release.
- Surfaces: Sessions, Replay, Metrics, Vault, Audit log.
- Auth: shared API key in `X-Wake-API-Key` header (localStorage on
  client side).
- Self-host: Docker Compose stack + Helm chart.
- Telemetry: structured logs from the Next.js route handler; the
  backend already exports OTel traces if `OTEL_EXPORTER_OTLP_ENDPOINT`
  is set.

### Planned for v1.0

- SSO (OIDC / SAML) instead of API keys.
- Durable audit log in Postgres.
- Per-credential scoping by agent.
- Webhook subscriptions for vault events.
