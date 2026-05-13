# CONTEXT — Wake (2026-05-13 16:30)

Briefing pra retomar em sessão nova. Wake é um substrato durável open-source pra agentes de IA, inspirado no Anthropic Managed Agents mas framework-agnostic via HarnessAdapter ABI.

---

## TL;DR

- **Repo público:** https://github.com/raphaelchristi/wake (conta `raphaelchristi`)
- **HEAD main:** `3c06d28` (working tree clean exceto este `CONTEXT.md`)
- **Phases 0, 1, 2, 3, 4 ✅ done.** Spec `v0.1.0-frozen` + tag `v0.4.0-production`.
- **329 + 146 = 475 tests** total (com regressions conhecidas em pydantic-ai/crewai por upstream drift).
- **HarnessAdapter ABI publicada** + 4 reference adapters em 10/10 conformance.
- **Production stack shipped:** Postgres + sandbox-runtime + Infisical Vault + LiteLLM + agentgateway + Helm + Compose.
- **Próximo:** decidir entre Phase 5 = Operator UI (Wake Dashboard) ou Phase 5 = Public Launch. User pediu plano do dashboard (este sessão).

---

## Sessão atual (2026-05-13 ~14:55 → 16:30)

Executamos Phase 4 inteira via padrão multi-agent. Wall-clock orquestrado: ~37 min.

- **PHASE-4-CONTRACT.md** escrito (slices: postgres-store, sandbox-runtime, vault-llm-deploy)
- **3 worktrees** criadas + 3 Opus agents em paralelo, background, com prompts self-contained
- **Merges sequenciais** (postgres → sandbox → vault-llm-deploy), conflitos em `/pyproject.toml all-adapters` resolvidos manualmente
- **Tests pós-merge** verdes nos 4 packages novos + regressions claude-sdk/langgraph/conformance OK
- **README do repo** reescrito (banner image + badges + quickstart + adapter table + production stack + status table). Atualizado em 2 iterações pra evitar duplicação com texto do banner.
- **Tag** `v0.4.0-production` criada e pushed
- **Codex review** rodada (P2: CONTEXT.md desatualizado — agora corrigido por este arquivo)

---

## Current state

- **Branch:** `main`, sincronizado com `origin/main`
- **Working tree:** clean (exceto `CONTEXT.md` que é este arquivo)
- **Last commit:** `3c06d28 readme: drop title/tagline that the banner already shows`
- **Git tags relevantes:** `spec-v0.1.0-frozen` (fbee2da), `v0.4.0-production` (ed80791)
- **Active gh account:** `raphaelchristi`
- **Venv local:** `.venv/` Python 3.11.10, todos adapters instalados em modo editável apontando para paths do main (worktrees foram removidos)
- **Worktrees ativas:** nenhuma

### Tests (rodar separados por package)

```bash
source .venv/bin/activate
pytest tests/unit/ -q                                    # 171 pass / 5 fail (pre-existing httpx[socks])
pytest adapters/claude-sdk/tests/ -q                     # 14 pass
pytest adapters/conformance/tests/ -q                    # 29 pass
pytest adapters/langgraph/tests/ -q                      # 42 pass
pytest adapters/crewai/tests/ -q                         # 28 pass / 9 fail (upstream drift)
pytest adapters/pydantic-ai/tests/ -q                    # 21 pass / 10 fail (ToolReturnPart.outcome removed)
pytest adapters/postgres-store/tests/ -q                 # 18 pass / 37 skip (testcontainers gated)
pytest adapters/sandbox-runtime/tests/ -q                # 46 pass / 2 skip (integration gated)
pytest adapters/vault-infisical/tests/ -q                # 43 pass
pytest adapters/llm-litellm/tests/ -q                    # 39 pass
```

---

## Phase 4 — entregue

| Slice | Merge | Packages |
|---|---|---|
| postgres-store | `94feb07` | `wake-store-postgres` v0.1.0 + `src/wake/runtime/registry.py` (EntryPointRegistry[T]) + `src/wake/py.typed` |
| sandbox-runtime | `03f1fbd` | `wake-sandbox-runtime` v0.1.0 |
| vault-llm-deploy | `3647537` | `wake-vault-infisical` + `wake-llm-litellm` v0.1.0 + `deploy/` (Helm v0.4.0 + Compose + agentgateway) + `docs/DEPLOY*.md` (5 docs) + `examples/05/07/08` |

Exit criteria de PHASE-4-production-stack.md atendidos (Postgres backend, sandbox-runtime, Infisical vault, LiteLLM, agentgateway, multi-worker via advisory locks + heartbeat, Helm chart, Docker Compose, examples). Load test code existe (opt-in via `--run-load`); execução real depende de Docker host.

---

## Issues conhecidas (não bloqueantes)

1. **`pydantic-ai` upstream drift** — bumped pra `1.31.0` no reinstall; `ToolReturnPart.outcome` foi removido → 10 testes do `wake-adapter-pydantic-ai` quebram. Antes do Phase 4: 31/31 passing. Fix: pin `pydantic-ai<1.31` no adapter `pyproject.toml` + adaptar adapter.py.
2. **`wake-adapter-crewai`** — 9 testes failing após reinstall, provável upstream drift similar. Precisa investigação.
3. **`tests/unit/test_cli_client.py` 5 failures** — pre-existentes (`httpx[socks]` missing). Adicionar `httpx[socks]` em dev deps ou rewriting tests.
4. **Discovery loaders não wired no CLI** — `EntryPointRegistry` existe em `src/wake/runtime/registry.py` mas `src/wake/cli/main.py` não consome (`wake adapter list` / `wake store list` / `wake vault list` ainda não existem).
5. **CrewAI emite 224 warnings em testes** — Pydantic deprecation; não-actionable do nosso lado.
6. **Pydantic `ToolDescriptor.schema` shadow warning** em `wake.types.ToolDescriptor`. Considerar rename `input_schema` em RFC futura.
7. **Pytest collection cross-package** falha por `__init__.py` collisions; workaround é rodar por package (documentado). Conserto: `--import-mode=importlib` no conftest root.

---

## Próxima decisão (a tomar pelo user)

Roadmap atual prevê Phase 5 = Public Launch. Mas user pediu plano do **Wake Dashboard (operator UI)** — SPA Next.js/SvelteKit com sessions list, replay scrubber, drill-down de eventos, métricas, vault management. Decisões pendentes:

- **Posição na roadmap:** Phase 5 = Operator UI (empurra Public Launch pra 6) **ou** Phase 5 = Public Launch (Dashboard vira Phase 6, com launch mais minimalista)?
- **Stack frontend:** Next.js 15 (App Router + RSC) **vs** SvelteKit 2 (mais leve)?
- **Hosting:** Vercel **vs** Docker no Helm chart (mais alinhado com self-host first)?

Plano detalhado em `phases/PHASE-5-operator-ui.md` (este sessão).

---

## Sugestões de ordem (após Phase 4)

| Etapa | Esforço | Justificativa |
|---|---|---|
| **1. Fix tech debt** (pydantic-ai pin + CrewAI drift + httpx[socks] + CLI discovery wiring) | ~30-60 min | Base sólida antes do launch; má primeira impressão se quebrado |
| **2. Phase 5 — Operator UI (Wake Dashboard)** | ~3-5 semanas (4-6h multi-agent) | Demo killer pro launch; valida a tese end-to-end |
| **3. Phase 6 — Public Launch** | ~1h multi-agent | mkdocs site, asciinemas, HN/Reddit, PyPI real publish |
| **4. RFCs em aberto** | ad-hoc | Cleanup |

---

## Files-chave a revisitar

Pra Phase 5 (operator UI):

1. **[`phases/PHASE-5-operator-ui.md`](phases/PHASE-5-operator-ui.md)** — plano completo (escrito nesta sessão)
2. **[`docs/SPEC-EVENT-SCHEMA.md`](docs/SPEC-EVENT-SCHEMA.md)** — schema dos eventos que o dashboard exibe
3. **[`src/wake/api/`](src/wake/api/)** — FastAPI routes existentes (SSE streaming, sessions, agents)
4. **[`adapters/postgres-store/`](adapters/postgres-store/)** — backend Postgres pra produção
5. **[`adapters/vault-infisical/src/wake_vault_infisical/oauth.py`](adapters/vault-infisical/src/wake_vault_infisical/oauth.py)** — OAuth flows que UI pode disparar

Pra tech debt:

1. `adapters/pydantic-ai/pyproject.toml` — pin pydantic-ai
2. `adapters/pydantic-ai/src/wake_adapter_pydantic_ai/adapter.py:190` — `ToolReturnPart(outcome=...)` removido
3. `adapters/crewai/tests/` — investigar 9 failures
4. `pyproject.toml` raiz — adicionar `httpx[socks]` em dev deps
5. `src/wake/cli/main.py` — wire `wake.stores/sandboxes/vaults/llm_providers` discovery via `EntryPointRegistry`

---

## Commands pra rodar local

### Setup do zero (máquina nova)

```bash
cd /Users/raphael/Desktop/repos/managed-agents
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv pip install -e adapters/claude-sdk -e adapters/conformance \
                  -e adapters/langgraph -e adapters/crewai \
                  -e adapters/pydantic-ai \
                  -e adapters/postgres-store -e adapters/sandbox-runtime \
                  -e adapters/vault-infisical -e adapters/llm-litellm
```

### Subir stack production (self-host)

```bash
docker compose -f deploy/docker-compose.yml up    # API + worker + Postgres + redis + agentgateway + vault
helm install wake deploy/helm/wake                # Kubernetes
```

### Rodar todos os tests por package

```bash
source .venv/bin/activate
for path in tests/unit adapters/{claude-sdk,conformance,langgraph,crewai,pydantic-ai,postgres-store,sandbox-runtime,vault-infisical,llm-litellm}/tests; do
  echo "=== $path ==="
  pytest "$path" -q 2>&1 | tail -2
done
```

### Iniciar Phase 5 (operator UI)

```bash
# 1. Garantir branch limpa
git checkout main && git pull origin main

# 2. Ler phases/PHASE-5-operator-ui.md (plano completo)

# 3. Decidir stack (Next.js vs SvelteKit) e posição na roadmap (5 ou 6)

# 4. Escrever phases/PHASE-5-CONTRACT.md (modelo: PHASE-4-CONTRACT.md)

# 5. Criar worktrees (e.g. agent/dashboard-shell, agent/dashboard-sessions, agent/dashboard-replay)

# 6. Dispatch agents em paralelo

# 7. Merge sequencial + cleanup
```

---

## Cronologia

| Data | Marco | Commit/PR | Status |
|---|---|---|---|
| 2026-05-13 | Initial repo + design docs (12 markdowns) | `8f84df1` → `7430d3b` | shipped |
| 2026-05-13 | Phase 1 done (3 agents paralelos, 154 tests) | `f47f670` + `6cc1658` + `db427cc` + `d35d8c2` | shipped |
| 2026-05-13 | Phase 2 done (HarnessAdapter ABI + 4 packages) | `bdf2bda` + `1a40103` + `74da1d9` + `e9b85c7` | shipped |
| 2026-05-13 | Phase 3 done (3 framework adapters reais, 10/10) | `ec5da26` + `26ce97a` + `6248102` | shipped |
| 2026-05-13 | Phase 0 closed empirically + spec lock | `fbee2da` + tag `spec-v0.1.0-frozen` + `d802396` | shipped |
| 2026-05-13 | Phase 4 done (Production Stack) | `94feb07` + `03f1fbd` + `3647537` + tag `v0.4.0-production` | shipped |
| 2026-05-13 | README rewrite + banner | `7a3c981` + `333fc27` + `3c06d28` | shipped |
| (próximo) | Phase 5 — Operator UI **or** Public Launch | TBD | not_started |

---

## Roadmap (resumo)

| Fase | Status | Wall-clock |
|---|---|---|
| Phase 0 — Design Lock | ✅ done | (empirical) |
| Phase 1 — Skeleton | ✅ done | 28 min |
| Phase 2 — First Adapter | ✅ done | 35 min |
| Phase 3 — Spec Validation | ✅ done | 70 min |
| Phase 4 — Production Stack | ✅ done | 37 min |
| Phase 5 — Operator UI (Wake Dashboard) **ou** Public Launch | ⚪ next | ~3-5h |
| Phase 6 — outra das duas | ⚪ not_started | ~1-3h |

---

## Tone notes pra próxima sessão

- User pediu trabalho em **português**. Manter.
- User valoriza **ação rápida + multi-agent paralelo**. Padrão validado 4x.
- User aceita **honestidade sobre desvios e regressões** (pydantic-ai drift, crewai drift) quando documentado.
- User pediu plano do **Wake Dashboard** (operator UI) — Next.js/SvelteKit, sessions/replay/drill-down/metrics/vault. Aguarda decisão de stack + posição na roadmap.

---

*Last updated: 2026-05-13 16:30 — Phase 4 done + Phase 5 operator UI planning. CONTEXT.md atualizado para resolver finding P2 do Codex review.*
