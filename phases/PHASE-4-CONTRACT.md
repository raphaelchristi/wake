# Phase 4 Execution Contract — Production Stack

> Substituir componentes "dev-grade" da Phase 1 por production-grade: Postgres + sandbox-runtime + Infisical Vault + LiteLLM + agentgateway + Deploy.
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial.

---

## Pre-existing — não modificar

Estes paths estão **locked** ou são interface autoritativa. Read-only:

- `src/wake/types.py` — canonical types (locked v0.1.0)
- `src/wake/store/base.py` — `EventStore` / `AgentStore` / `EnvironmentStore` / `SessionStore` ABCs (autoritativo)
- `src/wake/store/sqlite.py` — reference impl (para Postgres backend matchar comportamento)
- `src/wake/sandbox/base.py` — `SandboxAdapter` ABC (autoritativo)
- `src/wake/sandbox/docker.py` — reference impl + fallback target
- `src/wake/adapters/` — HarnessAdapter Protocol (spec locked v0.1.0)
- `src/wake/runtime/` — dispatcher (não tocar)
- `adapters/claude-sdk/` — reference adapter (consultar pra padrões)
- `adapters/conformance/` — wake-test-conformance v0.1.0
- `tests/unit/fakes.py` — fakes runtime (não tocar)
- `docs/SPEC-HARNESS-ADAPTER.md` — locked v0.1.0
- `docs/SPEC-EVENT-SCHEMA.md` — locked v0.1.0

**Qualquer mudança em files locked exige RFC explícita — abortar e perguntar.**

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `postgres-store` | `wake-wt-postgres-store` | `agent/postgres-store` | `adapters/postgres-store/` + multi-worker (advisory locks + heartbeat) + load test |
| `sandbox-runtime` | `wake-wt-sandbox-runtime` | `agent/sandbox-runtime` | `adapters/sandbox-runtime/` + fallback graceful selector + Linux/macOS testing |
| `vault-llm-deploy` | `wake-wt-vault-llm-deploy` | `agent/vault-llm-deploy` | `adapters/vault-infisical/` + `adapters/llm-litellm/` + `deploy/` (Helm + Compose) + agentgateway sidecar + examples 05/07/08 |

Slices são **disjuntos no filesystem** — zero overlap esperado fora de `pyproject.toml` (entry points) e `phases/README.md` (status).

---

## Files ownership

### `postgres-store` owns

```
adapters/postgres-store/pyproject.toml                                  NEW
adapters/postgres-store/README.md                                       NEW
adapters/postgres-store/src/wake_store_postgres/__init__.py             NEW
adapters/postgres-store/src/wake_store_postgres/store.py                NEW  — PostgresStore (bundle)
adapters/postgres-store/src/wake_store_postgres/events.py               NEW  — PostgresEventStore (LISTEN/NOTIFY)
adapters/postgres-store/src/wake_store_postgres/agents.py               NEW  — PostgresAgentStore
adapters/postgres-store/src/wake_store_postgres/environments.py         NEW  — PostgresEnvironmentStore
adapters/postgres-store/src/wake_store_postgres/sessions.py             NEW  — PostgresSessionStore
adapters/postgres-store/src/wake_store_postgres/locks.py                NEW  — advisory locks helpers
adapters/postgres-store/src/wake_store_postgres/heartbeat.py            NEW  — worker heartbeat protocol
adapters/postgres-store/src/wake_store_postgres/models.py               NEW  — SQLAlchemy ORM rows
adapters/postgres-store/alembic.ini                                     NEW
adapters/postgres-store/alembic/env.py                                  NEW
adapters/postgres-store/alembic/versions/0001_initial_schema.py         NEW  — events partitioned by hash
adapters/postgres-store/tests/__init__.py                               NEW
adapters/postgres-store/tests/conftest.py                               NEW  — testcontainers fixture
adapters/postgres-store/tests/test_event_store.py                       NEW
adapters/postgres-store/tests/test_agent_store.py                       NEW
adapters/postgres-store/tests/test_environment_store.py                 NEW
adapters/postgres-store/tests/test_session_store.py                     NEW
adapters/postgres-store/tests/test_locks.py                             NEW  — pg_try_advisory_lock contention
adapters/postgres-store/tests/test_heartbeat.py                         NEW
adapters/postgres-store/tests/test_listen_notify.py                     NEW  — SSE fan-out
adapters/postgres-store/tests/load/test_1000_sessions.py                NEW  — load test (skip by default)
adapters/postgres-store/examples/quickstart.py                          NEW  — runnable example
```

### `sandbox-runtime` owns

```
adapters/sandbox-runtime/pyproject.toml                                 NEW
adapters/sandbox-runtime/README.md                                      NEW
adapters/sandbox-runtime/src/wake_sandbox_runtime/__init__.py           NEW
adapters/sandbox-runtime/src/wake_sandbox_runtime/adapter.py            NEW  — SandboxRuntimeAdapter(SandboxAdapter)
adapters/sandbox-runtime/src/wake_sandbox_runtime/config.py             NEW  — build srt JSON config
adapters/sandbox-runtime/src/wake_sandbox_runtime/subprocess_runner.py  NEW  — wrap @anthropic-ai/sandbox-runtime CLI
adapters/sandbox-runtime/src/wake_sandbox_runtime/selector.py           NEW  — select_sandbox_backend() fallback
adapters/sandbox-runtime/src/wake_sandbox_runtime/platform_detect.py    NEW  — Linux bwrap / macOS sandbox-exec
adapters/sandbox-runtime/tests/__init__.py                              NEW
adapters/sandbox-runtime/tests/conftest.py                              NEW
adapters/sandbox-runtime/tests/test_adapter.py                          NEW  — mock subprocess
adapters/sandbox-runtime/tests/test_config.py                           NEW
adapters/sandbox-runtime/tests/test_selector.py                         NEW  — fallback graceful
adapters/sandbox-runtime/tests/test_platform_detect.py                  NEW
adapters/sandbox-runtime/tests/integration/test_real_sandbox.py         NEW  — skip se npm/srt indisponível
adapters/sandbox-runtime/examples/restricted_bash.py                    NEW
```

### `vault-llm-deploy` owns

```
# Vault package
adapters/vault-infisical/pyproject.toml                                 NEW
adapters/vault-infisical/README.md                                      NEW
adapters/vault-infisical/src/wake_vault_infisical/__init__.py           NEW
adapters/vault-infisical/src/wake_vault_infisical/vault.py              NEW  — InfisicalVault(VaultAdapter)
adapters/vault-infisical/src/wake_vault_infisical/base.py               NEW  — VaultAdapter ABC
adapters/vault-infisical/src/wake_vault_infisical/proxy.py              NEW  — HTTPS proxy integration
adapters/vault-infisical/src/wake_vault_infisical/oauth.py              NEW  — GitHub/Slack/Notion OAuth flows
adapters/vault-infisical/src/wake_vault_infisical/cli.py                NEW  — `wake vault init/add/list/remove`
adapters/vault-infisical/tests/__init__.py                              NEW
adapters/vault-infisical/tests/test_vault.py                            NEW
adapters/vault-infisical/tests/test_oauth.py                            NEW  — mock OAuth providers
adapters/vault-infisical/tests/test_prompt_injection_protection.py      NEW  — exfil test
adapters/vault-infisical/tests/test_cli.py                              NEW

# LLM package
adapters/llm-litellm/pyproject.toml                                     NEW
adapters/llm-litellm/README.md                                          NEW
adapters/llm-litellm/src/wake_llm_litellm/__init__.py                   NEW
adapters/llm-litellm/src/wake_llm_litellm/provider.py                   NEW  — LiteLLMProvider(LLMProvider)
adapters/llm-litellm/src/wake_llm_litellm/base.py                       NEW  — LLMProvider ABC
adapters/llm-litellm/src/wake_llm_litellm/normalize.py                  NEW  — provider event normalization
adapters/llm-litellm/src/wake_llm_litellm/cost_tracking.py              NEW  — LiteLLM callbacks → events
adapters/llm-litellm/tests/__init__.py                                  NEW
adapters/llm-litellm/tests/test_provider.py                             NEW
adapters/llm-litellm/tests/test_normalize.py                            NEW
adapters/llm-litellm/tests/test_cost_tracking.py                        NEW
adapters/llm-litellm/tests/test_multi_provider.py                       NEW  — Anthropic/OpenAI/Ollama (mocked)

# Deploy
deploy/docker-compose.yml                                               NEW
deploy/docker-compose.dev.yml                                           NEW
deploy/Dockerfile                                                       NEW
deploy/agentgateway/config.yaml                                         NEW  — sidecar config
deploy/helm/wake/Chart.yaml                                             NEW
deploy/helm/wake/values.yaml                                            NEW
deploy/helm/wake/templates/_helpers.tpl                                 NEW
deploy/helm/wake/templates/deployment-api.yaml                          NEW
deploy/helm/wake/templates/deployment-worker.yaml                       NEW
deploy/helm/wake/templates/statefulset-postgres.yaml                    NEW
deploy/helm/wake/templates/deployment-agentgateway.yaml                 NEW
deploy/helm/wake/templates/deployment-vault.yaml                        NEW
deploy/helm/wake/templates/service.yaml                                 NEW
deploy/helm/wake/templates/configmap.yaml                               NEW
deploy/helm/wake/templates/secret.yaml                                  NEW
deploy/helm/wake/templates/ingress.yaml                                 NEW
deploy/README.md                                                        NEW

docs/DEPLOY.md                                                          NEW  — overview
docs/DEPLOY-DOCKER-COMPOSE.md                                           NEW
docs/DEPLOY-KUBERNETES.md                                               NEW
docs/DEPLOY-FLYIO.md                                                    NEW
docs/DEPLOY-AWS.md                                                      NEW

# Examples
examples/05-kill-and-resume/README.md                                   NEW
examples/05-kill-and-resume/run.py                                      NEW
examples/07-mcp-github/README.md                                        NEW
examples/07-mcp-github/run.py                                           NEW
examples/07-mcp-github/agentgateway.yaml                                NEW
examples/08-vault-credentials/README.md                                 NEW
examples/08-vault-credentials/run.py                                    NEW
```

---

## ACCEPTANCE CRITERIA por slice

### `postgres-store` done quando:

- [ ] `pip install -e adapters/postgres-store` funciona com `asyncpg`, `sqlalchemy[asyncio]>=2.0`, `alembic` instalados
- [ ] `from wake_store_postgres import PostgresStore` works
- [ ] `PostgresStore(dsn: str)` constructor + `await store.initialize()` cria schema via Alembic
- [ ] `PostgresStore` expõe `.events`, `.agents`, `.environments`, `.sessions` — todos passam ABC isinstance checks de `src/wake/store/base.py`
- [ ] Comportamento idêntico ao `SQLiteStore` (rodar mesmo conjunto de tests behavioral)
- [ ] **Particionamento** `events` por `HASH(session_id)` com 16 partições (configurável via env `WAKE_PG_EVENT_PARTITIONS`)
- [ ] **Índice BRIN** em `events.created_at`
- [ ] **LISTEN/NOTIFY**: `subscribe(session_id)` usa `LISTEN events_<id_short>` (channel name truncado pra <63 chars Postgres limit), com fallback de polling se NOTIFY falhar
- [ ] **Advisory locks**: `acquire_session_lock(session_id) → bool` via `pg_try_advisory_lock(hashtext(session_id))`
- [ ] **Heartbeat protocol**: `WorkerHeartbeat` task que renova lock a cada 10s + watchdog que detecta worker dead em <30s
- [ ] Alembic migration `0001_initial_schema` reproduz schema completo (idempotent + downable)
- [ ] Tests rodam via testcontainers-python (Postgres 16) — skippable se Docker indisponível
- [ ] Load test (1000 concurrent sessions) **runnable** com `pytest tests/load/ --run-load` — não bloqueia CI normal
- [ ] Load test report: p95 session creation <200ms; p95 first event <500ms
- [ ] ruff + mypy strict clean em owned paths
- [ ] README documenta: DSN format, env vars, partitioning trade-offs, exemplo quickstart

### `sandbox-runtime` done quando:

- [ ] `pip install -e adapters/sandbox-runtime` works
- [ ] `from wake_sandbox_runtime import SandboxRuntimeAdapter` works
- [ ] `SandboxRuntimeAdapter(srt_binary: str = "sandbox-runtime")` constructor
- [ ] `isinstance(SandboxRuntimeAdapter(), SandboxAdapter)` from `src/wake/sandbox/base.py` → True
- [ ] `provision(env)` builds srt JSON config + invoca subprocess + retorna `SandboxHandle`
- [ ] `execute(handle, tool, input)` wrappeia comando com srt sandbox spec + roda
- [ ] **Mandatory deny paths**: `~/.ssh`, `~/.aws`, `/etc/shadow` sempre bloqueados (override-proof)
- [ ] **Network proxy**: integra com agentgateway se `network_mode=proxied`
- [ ] **Platform detection**: Linux → bubblewrap; macOS → sandbox-exec; outros → raise `SandboxUnavailableError`
- [ ] **Fallback selector** `select_sandbox_backend(prefer="sandbox-runtime")` → tenta srt, cai pra Docker, log warning
- [ ] Tests passam com subprocess mockado (`unittest.mock.AsyncMock`)
- [ ] Integration test real opcional (skip se srt CLI ausente) — rodar example 02 + verificar `~/.ssh` denied
- [ ] Ubuntu 24.04+ gotcha documentado no README (`sysctl kernel.apparmor_restrict_unprivileged_userns=0`)
- [ ] ruff + mypy strict clean
- [ ] Example `restricted_bash.py` runnable (com fallback)

### `vault-llm-deploy` done quando:

**Vault:**
- [ ] `pip install -e adapters/vault-infisical` works
- [ ] `from wake_vault_infisical import InfisicalVault, VaultAdapter` works
- [ ] `VaultAdapter` ABC define `add/get_proxy_token/list/revoke` (extensão Phase 4)
- [ ] `InfisicalVault(infisical_url, token)` constructor
- [ ] **CLI** `wake vault init/add/list/remove` via Typer (registrar em `src/wake/cli/`... ⚠ esse é único path fora do worktree disjunto — ver Cross-cutting abaixo)
- [ ] OAuth flow para **GitHub, Slack, Notion** (3 providers — code → token → store)
- [ ] **Prompt injection test**: agent recebe instrução pra exfiltrar `$GITHUB_TOKEN` via curl; verifica que (a) token nunca aparece em log/event, (b) egress a host não-whitelisted falha
- [ ] Credenciais NUNCA aparecem em events (apenas placeholders `{{vault:github_token}}` substituídos no proxy)
- [ ] ruff + mypy strict clean

**LLM:**
- [ ] `pip install -e adapters/llm-litellm` works
- [ ] `from wake_llm_litellm import LiteLLMProvider, LLMProvider` works
- [ ] `LLMProvider` ABC com `create_message(model, messages, tools, **kwargs)`
- [ ] `LiteLLMProvider()` integra `litellm.acompletion` async
- [ ] Multi-provider test mockado: **anthropic/claude-sonnet**, **openai/gpt-4o**, **ollama/qwen2.5-coder** — tool use semantics normalizadas para Wake `tool_use`/`tool_result` events
- [ ] **Cost tracking** via LiteLLM `success_callback` → emite `cost_tracked` metadata em events
- [ ] README documenta degradação por provider (no caching com OpenAI, no thinking com Ollama, etc.)
- [ ] ruff + mypy strict clean

**Deploy:**
- [ ] `deploy/docker-compose.yml` sobe stack: wake-api + wake-worker + postgres-16 + redis + agentgateway + infisical-vault
- [ ] `docker compose up` em uma máquina limpa → API responde em http://localhost:8080/health
- [ ] `deploy/helm/wake/` lintável via `helm lint deploy/helm/wake`
- [ ] Helm `Chart.yaml` v0.4.0
- [ ] `values.yaml` documenta TODAS opções com defaults
- [ ] `docs/DEPLOY.md` linka pros 4 sub-docs (compose, k8s, fly.io, AWS)
- [ ] Sidecar `deploy/agentgateway/config.yaml` configurado pra MCP HTTP egress

**Examples:**
- [ ] `examples/05-kill-and-resume/run.py` runnable: sobe session, mata worker no meio do step, segundo worker resume em <60s, verifica final event seq
- [ ] `examples/07-mcp-github/run.py` runnable: usa GitHub MCP server via agentgateway com vault GitHub token (mock provider OK no test)
- [ ] `examples/08-vault-credentials/run.py` runnable: demonstra OAuth flow GitHub → store no Infisical → agent usa via placeholder

---

## Cross-cutting (cuidado!)

### `wake vault` CLI

O slice `vault-llm-deploy` precisa registrar comando Typer dentro de `src/wake/cli/`. Este é o único path locked que precisa ser **estendido** (não substituído).

**Convenção:**
- Agent **adiciona** subcommand via entry point Typer no `wake_vault_infisical` package (`[project.entry-points."wake.cli"]`)
- **Não** edita `src/wake/cli/main.py` diretamente
- Se o entry point loader não existir ainda no main CLI, criar um patch pequeno e **documentar no PR description** — orchestrator merge dará atenção

### `pyproject.toml` raiz (`/pyproject.toml`)

Cada slice adiciona seu adapter na seção `[project.optional-dependencies]`:

```toml
all-adapters = [
  "wake-adapter-claude-sdk",
  "wake-adapter-langgraph",
  "wake-adapter-crewai",
  "wake-adapter-pydantic-ai",
  "wake-store-postgres",            # postgres-store slice adiciona
  "wake-sandbox-runtime",           # sandbox-runtime slice adiciona
  "wake-vault-infisical",           # vault-llm-deploy slice adiciona
  "wake-llm-litellm",               # vault-llm-deploy slice adiciona
]
```

**Conflitos esperados em `/pyproject.toml`** — orchestrator resolve no merge.

### `phases/README.md`

Não tocar nos slices. Orchestrator atualiza status `Phase 4 → ✅ done` no fim.

---

## ENTRY POINTS

Cada package adiciona ao seu `pyproject.toml`:

```toml
# wake-store-postgres
[project.entry-points."wake.stores"]
postgres = "wake_store_postgres.store:create_from_dsn"

# wake-sandbox-runtime
[project.entry-points."wake.sandboxes"]
sandbox-runtime = "wake_sandbox_runtime.adapter:create"

# wake-vault-infisical
[project.entry-points."wake.vaults"]
infisical = "wake_vault_infisical.vault:create"
[project.entry-points."wake.cli"]
vault = "wake_vault_infisical.cli:app"

# wake-llm-litellm
[project.entry-points."wake.llm_providers"]
litellm = "wake_llm_litellm.provider:create"
```

Se o discovery loader para `wake.stores`/`wake.sandboxes`/`wake.vaults`/`wake.llm_providers` ainda não existir em `src/wake/runtime/registry.py` (já existe para `wake.adapters`), o slice `postgres-store` adiciona pattern análogo e os outros 2 slices consomem. **Coordenar**: postgres-store é o primeiro merge — dá o padrão.

---

## SHARED DECISIONS

### Versioning

- Cada package: `version = "0.1.0"` (PEP 440 — sem suffix)
- Spec `compatibility`: `"wake-harness-adapter@^0.1"` quando aplicável (sandbox segue `wake-sandbox-adapter`)

### Python version

- `>=3.11` em todos os packages

### Frameworks pinning

- `asyncpg>=0.29` + `sqlalchemy[asyncio]>=2.0` + `alembic>=1.13` (postgres-store)
- npm `@anthropic-ai/sandbox-runtime` invocado por subprocess (sandbox-runtime) — **não há pip dep**
- `infisical-python>=1.0` + `requests-oauthlib>=2.0` (vault-infisical)
- `litellm>=1.50` (llm-litellm)

### Tests

- **Sem real LLM calls** (sempre mock)
- **Sem real OAuth flows** (mock providers via `responses` lib)
- **Postgres tests** usam `testcontainers-python` — skippable
- **sandbox-runtime real test** — skippable se npm/srt CLI ausentes
- **Load test** — opt-in via `--run-load`

### Logging

- `structlog.get_logger(__name__)` (segue padrão do projeto)
- **JAMAIS** logar valor de token/credential
- **JAMAIS** logar conteúdo de event payload com placeholders substituídos

### MyPy strict

- `mypy --strict` clean em owned paths
- Tipos canônicos vêm de `wake.types` — não redefinir

---

## MERGE ORDER

Quando todos terminarem:

1. **`postgres-store`** → main (zero conflito esperado; estabelece registry pattern; é a base)
2. **`sandbox-runtime`** → main (conflito esperado: `/pyproject.toml` `all-adapters`)
3. **`vault-llm-deploy`** → main (conflito esperado: `/pyproject.toml` + possível CLI shim)

Após cada merge, orchestrator roda:

```bash
source .venv/bin/activate
pytest tests/unit/ -q                                    # 176 baseline
pytest adapters/<just-merged>/tests/ -q                  # nova suite
```

Se quebrar suite de outro adapter, **STOP** — investigar regressão.

---

## CONVENÇÕES

- Python 3.11+, async/await, ruff format, mypy strict
- Commit messages com prefixo: `postgres:`, `sandbox-runtime:`, `vault:`, `litellm:`, `deploy:`, `examples:`
- Cada agent trabalha **EXCLUSIVAMENTE no seu worktree** (`wake-wt-<slice>/`)
- **Não tocar** files de outros slices
- **Não tocar** files locked (lista em "Pre-existing")
- Tests sem real LLM/OAuth/infra externa (mock everything)
- Cada package tem seu próprio `pyproject.toml` (instalável `-e`)

---

## DELIVERABLES por agent (resumo)

| Slice | Packages | Tests | Examples/Docs |
|---|---|---|---|
| postgres-store | `wake-store-postgres` (1 pkg + Alembic migrations) | ~9 test files + load test | 1 quickstart + README |
| sandbox-runtime | `wake-sandbox-runtime` (1 pkg) | ~6 test files | 1 example + README |
| vault-llm-deploy | `wake-vault-infisical` + `wake-llm-litellm` (2 pkgs) + Helm chart + Compose | ~9 test files | 3 examples + 5 deploy docs |

---

## REGRA DE OURO

1. **Leia este contrato + PHASE-4-production-stack.md + `src/wake/store/base.py` + `src/wake/sandbox/base.py` ANTES de codar.**
2. **Use as ABCs de `src/wake/store/base.py` / `src/wake/sandbox/base.py` EXATAMENTE.**
3. **Match comportamento do SQLite store / Docker sandbox** (mesma semântica, infra diferente).
4. **NÃO toque** em files de outros slices nem em files locked.
5. **Commit no SEU worktree** (`wake-wt-<slice>/`), branch `agent/<slice>`.
6. **Estimativa**: 90-180min wall-clock por slice (Phase 4 é mais pesada que Phases 2/3 — infra real).
7. **Quando terminar**: reporte (a) tests passando por suite, (b) deliverables checked, (c) qualquer file fora do seu slice tocado (raro mas pode acontecer em pyproject root).
