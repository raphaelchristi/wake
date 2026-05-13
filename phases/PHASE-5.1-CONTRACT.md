# Phase 5.1 Execution Contract — Adversarial Review Fixes

> Resolver 6 findings da Codex adversarial review (3 critical + 3 high).
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial.

---

## Background — findings em escopo

1. **[CRITICAL] API server sobe vazio** (`src/wake/cli/main.py:205-207`) — `wake server` invoca `uvicorn wake.api.app:app` mas o `app` module-level é `create_app()` sem wiring.
2. **[CRITICAL] `wake worker` command não existe** — Helm + Compose chamam `wake worker --concurrency N` mas CLI só tem `server` e `run`.
3. **[CRITICAL] Auth fail-open em deploy** (`src/wake/api/dependencies.py:142-156`) — `verify_api_key` retorna sem checar quando `WAKE_API_KEY` env vazia; deploy não seta.
4. **[HIGH] OAuth state per-process** (`src/wake/api/routes/vault.py:200-226`) — `oauth_flows` é dict em memória; Helm default `replicas=2` quebra start→callback.
5. **[HIGH] Rotate cria credential nova** (`src/wake/api/routes/vault.py:248-256`) — callback não carrega `vault_id` original, faz `vault.add(...)` em vez de replace+revoke.
6. **[HIGH] Frontend env vars mismatch** — Helm/Compose setam `NEXT_PUBLIC_API_URL`+`WAKE_API_URL`, código lê `NEXT_PUBLIC_WAKE_API_BASE`.

---

## Pre-existing — não modificar

- `src/wake/types.py`, `src/wake/store/*`, `src/wake/sandbox/*`, `src/wake/adapters/*`, `src/wake/runtime/*` (exceto dispatcher se necessário, locked v0.1.0)
- `docs/SPEC-HARNESS-ADAPTER.md`, `docs/SPEC-EVENT-SCHEMA.md`
- `adapters/*` (exceto `vault-infisical` que recebe rotate semantic fix — additive only, no breaking)
- `phases/PHASE-*-CONTRACT.md` anteriores

---

## Divisão de slices

| Agent | Worktree | Branch | Owns | Findings |
|---|---|---|---|---|
| `api-bootstrap` | `wake-wt-fix-api-bootstrap` | `fix/api-bootstrap` | Real bootstrap pra `wake server` + novo `wake worker` command + Dockerfile entrypoint + smoke tests | #1, #2 |
| `auth-env-canon` | `wake-wt-fix-auth-env-canon` | `fix/auth-env-canon` | Auth fail-closed default + canonical env var name `NEXT_PUBLIC_WAKE_API_BASE`/`WAKE_API_URL` em todo deploy + tests | #3, #6 |
| `vault-state-rotate` | `wake-wt-fix-vault-state-rotate` | `fix/vault-state-rotate` | OAuth state via signed/encoded blob (stateless) + rotate carry `vault_id` + revoke old + tests | #4, #5 |

---

## Files ownership

### `api-bootstrap` owns

```
src/wake/api/bootstrap.py                                   NEW  — production app factory reading env
src/wake/cli/main.py                                        UPDATE  — `server` real bootstrap + new `worker` cmd
src/wake/runtime/worker.py                                  NEW  — worker loop (acquires advisory locks, drains queue)
tests/unit/test_bootstrap.py                                NEW
tests/unit/test_cli_worker.py                               NEW
docs/DEPLOY.md                                              UPDATE  — minimal env var reference (or NEW if missing)
```

### `auth-env-canon` owns

```
src/wake/api/dependencies.py                                UPDATE  — fail-closed when WAKE_AUTH_REQUIRED=true (default in prod)
src/wake/api/app.py                                         UPDATE  — read WAKE_AUTH_REQUIRED, warn if disabled
deploy/docker-compose.yml                                   UPDATE  — set WAKE_API_KEY (default rand?), rename env vars frontend
deploy/helm/wake/values.yaml                                UPDATE  — apiKey block + canonical env names
deploy/helm/wake/templates/deployment-api.yaml              UPDATE  — inject WAKE_API_KEY from secret
deploy/helm/wake/templates/deployment-frontend.yaml         UPDATE  — replace NEXT_PUBLIC_API_URL/WAKE_API_URL with canonical
deploy/helm/wake/templates/secret.yaml                      UPDATE  — wake-api-key entry
deploy/Dockerfile.frontend                                  UPDATE  — comment block uses canonical names
docs/DASHBOARD.md                                           UPDATE  — env var section consistent
tests/unit/test_auth_required.py                            NEW
```

### `vault-state-rotate` owns

```
src/wake/api/routes/vault.py                                UPDATE  — sign OAuth state via HMAC (stateless), carry vault_id, replace+revoke on rotate
src/wake/api/oauth_state.py                                 NEW  — sign/verify helpers (HMAC-SHA256, base64url, TTL via timestamp)
adapters/vault-infisical/src/wake_vault_infisical/vault.py  UPDATE  — add `replace(vault_id, ...)` or `update_and_revoke_old` method
tests/unit/test_oauth_state.py                              NEW
tests/unit/test_vault_routes.py                             UPDATE  — test multi-replica scenario + rotate semantics
```

---

## Cross-cutting (cuidado!)

### `deploy/helm/wake/values.yaml`

Tocado por **auth-env-canon** principalmente. Se `api-bootstrap` precisar adicionar uma chave nova (ex: `replicas` para API quando OAuth não estiver durable), faça em commit separado claramente marcado para facilitar merge.

### `src/wake/cli/main.py`

**Apenas** `api-bootstrap` toca. Outros slices não.

### `src/wake/api/app.py`

**Apenas** `auth-env-canon` toca (para ler `WAKE_AUTH_REQUIRED` env). `vault-state-rotate` não toca; rotas vivem em `routes/vault.py`.

---

## ACCEPTANCE CRITERIA por slice

### `api-bootstrap` done quando:

- [ ] `src/wake/api/bootstrap.py` lê env vars: `WAKE_DATABASE_URL` (default `sqlite+aiosqlite:///./wake.db`), `WAKE_SANDBOX_BACKEND` (default `docker`), `WAKE_VAULT_PROVIDER` (default none), `WAKE_API_KEY`, `WAKE_API_CORS_ORIGINS`.
- [ ] `bootstrap.create_production_app()` retorna FastAPI com TODOS os componentes wired (stores, dispatcher, adapter registry, vault opcional).
- [ ] `wake server` CLI command usa essa factory ao invés do module-level vazio.
- [ ] `wake worker` CLI command novo: lê DSN, conecta no store, roda loop que (a) acquire session via advisory lock, (b) drain step events via dispatcher, (c) heartbeat task, (d) graceful shutdown em SIGTERM.
- [ ] `wake worker --concurrency N` aceita arg (paralelismo via asyncio Tasks).
- [ ] Smoke test: `pytest tests/unit/test_bootstrap.py -q` cria session via TestClient + verifica `GET /v1/sessions` retorna a session.
- [ ] Smoke test: `pytest tests/unit/test_cli_worker.py -q` mocka store + dispatcher, executa worker loop por N ciclos.
- [ ] Em vez do `app = create_app()` module-level, deixar callable `get_app()` que carrega lazy via bootstrap. Compat: manter `app = get_app()` no fim do `app.py` ou eq. Documentar.
- [ ] `mypy --strict` clean nas adições; ruff clean.

### `auth-env-canon` done quando:

- [ ] `verify_api_key` aceita modo "required":
  - Default: se `WAKE_API_KEY` setada, exige; se vazia, no-op (compat dev).
  - Novo flag `WAKE_AUTH_REQUIRED=true` (env) força auth mesmo sem chave (rejeita TODAS as requests com 503 "no key configured"), evita fail-open em prod.
  - Helm + Compose setam `WAKE_AUTH_REQUIRED=true` por default.
- [ ] `WAKE_API_KEY` é injetado nos manifests via Secret (Helm) / `${WAKE_API_KEY}` (Compose).
- [ ] Helm `values.yaml` ganha bloco `auth: {apiKey: "", apiKeySecretRef: ""}` com docs claros.
- [ ] Frontend env vars canonicalizados: **apenas** `NEXT_PUBLIC_WAKE_API_BASE` (browser-facing) e `WAKE_API_URL` (server-side OAuth callback proxy). Remover `NEXT_PUBLIC_API_URL`.
- [ ] OAuth callback `frontend/src/app/oauth/callback/api/route.ts` lê `WAKE_API_URL` quando setado, caindo pra `NEXT_PUBLIC_WAKE_API_BASE` como fallback.
- [ ] Compose + Helm + Dockerfile.frontend + docs/DASHBOARD.md + frontend/README todos consistentes.
- [ ] `tests/unit/test_auth_required.py`:
  - test_no_key_no_required → no-op (200 OK)
  - test_key_set_no_header → 401
  - test_key_set_correct_header → 200
  - test_auth_required_no_key → 503 (`auth required but not configured`)
- [ ] `helm lint deploy/helm/wake` clean; `docker compose -f deploy/docker-compose.yml config` valida.

### `vault-state-rotate` done quando:

- [ ] `src/wake/api/oauth_state.py`:
  - `sign_state(payload: dict, secret: str, ttl_seconds: int = 600) -> str` → base64url(HMAC(payload + ts)).
  - `verify_state(token: str, secret: str) -> dict` → raises se inválido/expired.
  - Secret read from env `WAKE_OAUTH_STATE_SECRET` (auto-generated at process start if absent, logged warning).
- [ ] `routes/vault.py`:
  - `POST /v1/vault/oauth/start` retorna `state` como signed token contendo `{provider, scopes, redirect_uri, vault_id_to_rotate?}`.
  - `GET /v1/vault/oauth/callback?code=&state=` decodifica state, valida, troca code por token, **se** `vault_id_to_rotate` presente: chama `vault.replace(vault_id, new_token)` + audit `rotated`; senão `vault.add(...)`.
  - Remove `app_state.oauth_flows` dict (não mais necessário) — manter compat reading old format por um patch release com deprecation warning.
- [ ] `wake_vault_infisical.vault.replace(vault_id, new_credential)` adicionado: atomic replace + revoke old (graceful: se Infisical não suporta atomic, faz add new → revoke old).
- [ ] `tests/unit/test_oauth_state.py`: sign+verify roundtrip, expired token, tampered token.
- [ ] `tests/unit/test_vault_routes.py` ganha:
  - test_oauth_callback_works_across_replicas (simula 2 instances trocando state)
  - test_rotate_replaces_credential (1 credential antes, 1 credential depois com novo token, audit `rotated` presente)
- [ ] `mypy --strict` clean; ruff clean.

---

## SHARED DECISIONS

### Auth modes (canonical)

| Env | Behavior |
|---|---|
| `WAKE_API_KEY` unset, `WAKE_AUTH_REQUIRED` unset/false | No-op (dev mode, header ignored) |
| `WAKE_API_KEY=<key>`, `WAKE_AUTH_REQUIRED` unset | Header must match (production) |
| `WAKE_AUTH_REQUIRED=true`, `WAKE_API_KEY` unset | All authenticated routes return 503 |
| `WAKE_AUTH_REQUIRED=true`, `WAKE_API_KEY=<key>` | Same as #2 (header must match) |

### Frontend env var canon

- **`NEXT_PUBLIC_WAKE_API_BASE`** — browser-facing API origin (used by `lib/api/client.ts`). Public, baked into client bundle.
- **`WAKE_API_URL`** — server-side proxying (Node route handlers like OAuth callback). Private, never exposed to client.

Deprecated: `NEXT_PUBLIC_API_URL` (alias kept in `client.ts` for 1 release with deprecation log, then removed).

### Versioning

- Package `wake-ai` permanece `0.0.1`.
- Frontend `wake-dashboard` permanece `0.5.0`.
- Helm Chart bumps `0.4.0` → `0.5.1`.
- Tag: `v0.5.1-fixes`.

### Convenções

- Python 3.11+, ruff, mypy strict, structlog.
- Commit prefixes: `api:`, `cli:`, `worker:`, `auth:`, `deploy:`, `vault:`, `oauth:`, `docs:`, `tests:`.
- Cada slice **EXCLUSIVAMENTE no seu worktree** (`wake-wt-fix-*`).

---

## MERGE ORDER

1. **`auth-env-canon`** → main (menor; estabelece env var canon)
2. **`api-bootstrap`** → main (conflito esperado: `src/wake/cli/main.py` se shared; `deploy/*.yaml` env vars já canonicalizados)
3. **`vault-state-rotate`** → main (conflito esperado: `src/wake/api/routes/vault.py`, `tests/unit/test_vault_routes.py`)

Após cada merge:
```bash
source .venv/bin/activate
pytest tests/unit/ -q
pytest adapters/vault-infisical/tests/ -q
helm lint deploy/helm/wake 2>/dev/null || true
docker compose -f deploy/docker-compose.yml config > /dev/null
```

---

## REGRA DE OURO

1. **Leia este contrato + Codex review findings + `docs/SPEC-EVENT-SCHEMA.md` ANTES de codar.**
2. **Backend additions ADDITIVE — não muda shape de rotas existentes (mas pode mudar comportamento de auth/state, é o ponto).**
3. **Compat backward: dev mode (sem env vars) ainda deve funcionar pra `wake run` e `wake server` local.**
4. **Tests Python: sem real Postgres/OAuth/Infisical — usar SQLite + mocks.**
5. **Commit no SEU worktree** (`wake-wt-fix-<slice>/`), branch `fix/<slice>`.
6. **Commits atômicos por componente** — se cair, perda mínima.
7. **Quando terminar**: reporte tests passando, files fora do slice, desvios.
8. **NÃO PUSH. NÃO MERGE.** Orchestrator faz.
