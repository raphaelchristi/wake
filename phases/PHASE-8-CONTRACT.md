# Phase 8 Execution Contract — Developer Experience

> Tier 2 gaps (#9–#12): SDKs · edit-and-replay · eval framework · versioning UI.
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial A → B → C.
>
> **Baseline:** `v0.7.0-ops-hardening` (Phase 7 done). Ops endpoints + Prometheus disponíveis.

---

## Decisões locked

| Decisão | Valor | Justificativa |
|---|---|---|
| Python SDK | **`wake-py`** package, typed, async-first, sync facade opcional | Padrão Anthropic SDK; `httpx` + `pydantic` stack |
| Python SDK transport | `httpx.AsyncClient` + SSE via `httpx-sse` | Mantém streaming consistente com dashboard |
| Python SDK shape | `client.sessions.create()`, `client.sessions.stream()`, `client.agents.list()` | Mirror Anthropic SDK + Managed Agents conventions |
| Python SDK distribution | PyPI (`wake-ai-client`) + GitHub release | Não confundir com `wake-ai` (server package) |
| TS SDK | **`@wake-ai/client`** package, fetch-based + EventSource polyfill | Browser + Node compat |
| TS SDK distribution | npm + GitHub Packages mirror | Self-host friendly |
| Eval framework | `wake eval` CLI + `wake-evals` package separado | Reuses adapter pattern (eval drivers) |
| Eval dataset format | JSONL: `{input, expected, metadata}` linha-a-linha | Compat LangSmith/Phoenix datasets |
| Eval metrics | cost_usd / latency_p95 / accuracy (custom scorer) | Mínimo viável; estende via plugin |
| Eval drivers | LangSmith adapter (`wake-eval-langsmith`) + Phoenix adapter (`wake-eval-phoenix`) | Self-hosted Phoenix + cloud LangSmith |
| Edit-and-replay | Frontend page `/sessions/[id]/edit` + backend `POST /v1/sessions/{id}/replay` | Server-side replay com seed control |
| Replay diff | Side-by-side render eventos original vs novo; highlight diffs | UX: scrubber duplo |
| Agent versioning UI | Dashboard página `/agents/[id]/versions` com diff entre versões + canary | Backend já versiona; UI faltava |
| Canary deploy | `agent.metadata.canary_weight: <0-100>` percentual de novas sessões usa nova versão | Server-side weighted random |
| Migration docs | `docs/MIGRATION-FROM-LANGGRAPH.md` + `docs/MIGRATION-FROM-MANAGED-AGENTS.md` | Tier 3 mas overlap aqui |

---

## Pre-existing — não modificar

- Stores Protocols + RBAC + tenancy (Phase 6)
- Rate-limit + idempotency + Prometheus (Phase 7)
- `src/wake/types.py` core schemas — additive only
- Specs

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `dx-sdks` | `wake-wt-dx-sdks` | `agent/dx-sdks` | `wake-py` + `wake-ts` SDKs (separate packages, separate releases) |
| `dx-eval` | `wake-wt-dx-eval` | `agent/dx-eval` | `wake eval` CLI + `wake-evals` package + LangSmith/Phoenix adapters |
| `dx-edit-replay` | `wake-wt-dx-edit-replay` | `agent/dx-edit-replay` | Edit-and-replay backend route + frontend page + versioning diff UI + canary + migration docs |

---

## Files ownership

### `dx-sdks` owns

```
# Python SDK
sdks/python/                                                     NEW DIR
sdks/python/pyproject.toml                                       NEW (wake-ai-client 0.1.0)
sdks/python/src/wake_ai_client/__init__.py                       NEW
sdks/python/src/wake_ai_client/client.py                         NEW (WakeClient)
sdks/python/src/wake_ai_client/sessions.py                       NEW
sdks/python/src/wake_ai_client/agents.py                         NEW
sdks/python/src/wake_ai_client/events.py                         NEW
sdks/python/src/wake_ai_client/sse.py                            NEW
sdks/python/src/wake_ai_client/types.py                          NEW (re-export from wake.types via openapi)
sdks/python/src/wake_ai_client/exceptions.py                     NEW
sdks/python/tests/test_client.py                                 NEW
sdks/python/tests/test_sessions.py                               NEW
sdks/python/tests/test_sse.py                                    NEW
sdks/python/README.md                                            NEW (≥300 linhas, quickstart + API + auth)

# TS SDK
sdks/typescript/                                                 NEW DIR
sdks/typescript/package.json                                     NEW (@wake-ai/client 0.1.0)
sdks/typescript/tsconfig.json                                    NEW
sdks/typescript/src/index.ts                                     NEW
sdks/typescript/src/client.ts                                    NEW (WakeClient)
sdks/typescript/src/sessions.ts                                  NEW
sdks/typescript/src/agents.ts                                    NEW
sdks/typescript/src/sse.ts                                       NEW (EventSource + fetch fallback)
sdks/typescript/src/types.ts                                     NEW
sdks/typescript/tests/client.test.ts                             NEW (vitest)
sdks/typescript/tests/sse.test.ts                                NEW
sdks/typescript/README.md                                        NEW (≥300 linhas)

# CI
.github/workflows/sdk-python-ci.yml                              NEW (pytest + build + publish-to-test-pypi on tag)
.github/workflows/sdk-typescript-ci.yml                          NEW (vitest + build + publish-to-npm on tag)

# Docs
docs/SDK-PYTHON.md                                               NEW (≥200 linhas — quickstart + auth + streaming + retries)
docs/SDK-TYPESCRIPT.md                                           NEW (≥200 linhas)
```

### `dx-eval` owns

```
# Eval CLI
src/wake/eval/__init__.py                                        NEW
src/wake/eval/runner.py                                          NEW (read dataset → run via SDK → collect → score)
src/wake/eval/dataset.py                                         NEW (JSONL reader)
src/wake/eval/scorer.py                                          NEW (default scorers: exact_match, regex, llm_judge)
src/wake/eval/report.py                                          NEW (markdown + JSON output)
src/wake/cli/eval.py                                             NEW (wake eval run/list/show)
src/wake/cli/__init__.py                                         UPDATE (register eval subcommand)

# wake-evals package (reuse adapter pattern)
adapters/eval-langsmith/                                         NEW DIR
adapters/eval-langsmith/pyproject.toml                           NEW
adapters/eval-langsmith/src/wake_eval_langsmith/__init__.py      NEW
adapters/eval-langsmith/src/wake_eval_langsmith/adapter.py       NEW
adapters/eval-langsmith/tests/test_adapter.py                    NEW

adapters/eval-phoenix/                                           NEW DIR
adapters/eval-phoenix/pyproject.toml                             NEW
adapters/eval-phoenix/src/wake_eval_phoenix/__init__.py          NEW
adapters/eval-phoenix/src/wake_eval_phoenix/adapter.py           NEW
adapters/eval-phoenix/tests/test_adapter.py                      NEW

# Tests
tests/unit/test_eval_runner.py                                   NEW
tests/unit/test_eval_dataset.py                                  NEW
tests/unit/test_eval_scorer.py                                   NEW

# Docs
docs/EVAL-FRAMEWORK.md                                           NEW (≥400 linhas — quickstart, scorer plugin, drivers, CI integration)
docs/EVAL-DATASET-FORMAT.md                                      NEW (≥150 linhas — schema + examples + LangSmith/Phoenix compat)
```

### `dx-edit-replay` owns

```
# Backend
src/wake/api/routes/replay.py                                    NEW (POST /v1/sessions/{id}/replay)
src/wake/runtime/replay_engine.py                                NEW (deterministic replay with overrides)
src/wake/api/app.py                                              UPDATE (include_router replay)
src/wake/types.py                                                UPDATE (ReplayRequest, ReplayResult)

# Canary
src/wake/runtime/canary.py                                       NEW (weighted version selection)
src/wake/store/base.py                                           UPDATE (AgentStore.create_session_with_canary helper)
src/wake/store/sqlite.py                                         UPDATE

# Frontend — Edit & Replay
frontend/src/app/(authed)/sessions/[id]/edit/page.tsx            NEW
frontend/src/components/replay/SessionEditor.tsx                 NEW (system prompt editor + tools)
frontend/src/components/replay/ReplayDiff.tsx                    NEW (side-by-side scrubber)
frontend/src/hooks/useReplay.ts                                  NEW

# Frontend — Versioning
frontend/src/app/(authed)/agents/[id]/versions/page.tsx          NEW
frontend/src/components/agents/AgentVersionDiff.tsx              NEW
frontend/src/components/agents/CanaryControl.tsx                 NEW
frontend/src/hooks/useAgentVersions.ts                           NEW

# Tests
tests/unit/test_replay_engine.py                                 NEW
tests/unit/test_canary.py                                        NEW
tests/unit/test_api_replay.py                                    NEW
frontend/tests/unit/replay-diff.test.tsx                         NEW
frontend/tests/unit/canary-control.test.tsx                      NEW
frontend/tests/e2e/edit-replay.spec.ts                           NEW

# Docs
docs/EDIT-AND-REPLAY.md                                          NEW (≥300 linhas — workflow + determinism guarantees + limitations)
docs/AGENT-VERSIONING.md                                         NEW (≥250 linhas — create version + diff + canary deploy)
docs/MIGRATION-FROM-LANGGRAPH.md                                 NEW (≥500 linhas — concrete code samples)
docs/MIGRATION-FROM-MANAGED-AGENTS.md                            NEW (≥500 linhas — mapping + gotchas)
```

---

## Cross-cutting

- `src/wake/api/app.py`: slice C adiciona replay router. Outros não tocam.
- `src/wake/types.py`: slice C adiciona ReplayRequest/Result. Outros não tocam.
- `src/wake/cli/__init__.py`: slice B registra eval subcommand. Outros não tocam (sdk não toca CLI server).
- `pyproject.toml` raiz: slice A NÃO toca (SDK é package separado em `sdks/`). Slice B adiciona `wake-evals` como extras opcionais. Slice C não toca.

---

## ACCEPTANCE CRITERIA

### `dx-sdks` done quando:

- [ ] `wake-py`: `WakeClient(base_url, api_key, organization_id, workspace_id)` factory
- [ ] Methods: `client.sessions.create/list/get/delete/interrupt`, `client.sessions.stream(id) -> AsyncIterator[Event]`, `client.agents.*`
- [ ] Typed via pydantic models (re-export de wake types)
- [ ] Retry logic com backoff em 5xx + 429 (respeita Retry-After)
- [ ] `WAKE_API_KEY` env var fallback
- [ ] Tests: `test_client` (auth + base_url validation), `test_sessions` (CRUD), `test_sse` (stream + reconnect)
- [ ] `wake-ts`: equivalente em TypeScript com mesma API surface
- [ ] Browser + Node compat (`fetch` + `EventSource` polyfill)
- [ ] Bundle <30KB gzip
- [ ] `pytest sdks/python/tests/` clean
- [ ] `cd sdks/typescript && pnpm vitest run` clean
- [ ] `python -c "import wake_ai_client; print(wake_ai_client.__version__)"` works
- [ ] `wake-py` README ≥300 linhas com quickstart, auth, streaming, retries, examples
- [ ] `wake-ts` README idem
- [ ] CI workflows pra build + publish (não publish em PR; só em tags `sdk-py-v*` e `sdk-ts-v*`)

### `dx-eval` done quando:

- [ ] `wake eval run --dataset golden.jsonl --agent <id> --output report.md`
- [ ] Suporta scorers built-in: `exact_match`, `regex`, `llm_judge`
- [ ] Plugin scorer via entry_points
- [ ] LangSmith adapter pode pull dataset + push results
- [ ] Phoenix adapter pode pull dataset + push results
- [ ] Output: markdown table + JSON detalhado
- [ ] Tests: runner integration, dataset parse, scorers, adapters mock
- [ ] `docs/EVAL-FRAMEWORK.md` ≥400 linhas
- [ ] `docs/EVAL-DATASET-FORMAT.md` ≥150 linhas

### `dx-edit-replay` done quando:

- [ ] `POST /v1/sessions/{id}/replay` aceita `{system_prompt?, tools?, max_steps?}` overrides + retorna `new_session_id`
- [ ] Deterministic replay: mesma seed → mesmo output (modulo overrides)
- [ ] Canary: `agent.metadata.canary_weight` (0-100) define % de sessões usa canary version
- [ ] Frontend `/sessions/[id]/edit` page funcional
- [ ] Side-by-side diff render (ReplayDiff component)
- [ ] `/agents/[id]/versions` mostra timeline + diff entre adjacent versions
- [ ] Canary control UI (slider + apply)
- [ ] Tests: backend (replay determinism + canary distribution), frontend (vitest + 1 e2e)
- [ ] Migration guides ≥500 linhas cada com concrete code samples

**Quality (todos):**
- [ ] Sem regressão suites baseline
- [ ] ruff + mypy strict + tsc strict clean
- [ ] Commit prefixes: `sdk:`, `eval:`, `replay:`, `versioning:`, `docs:`, `tests:`

---

## MERGE ORDER

1. **`dx-sdks`** → main (zero overlap; SDKs em diretório separado)
2. **`dx-eval`** → main (CLI server + adapters; conflito potencial em pyproject.toml extras)
3. **`dx-edit-replay`** → main (backend + frontend; conflito potencial em app.py + types.py)

Tag final: `v0.8.0-dx`.

---

## REGRA DE OURO

1. **Leia contract + `docs/ROADMAP.md` Tier 2 + `phases/PHASE-7-CONTRACT.md` ANTES de codar.**
2. **SDKs são packages separados** — não modificam `src/wake/` server-side.
3. **Replay é deterministic** — overrides só substituem system_prompt/tools/max_steps; seeds preserved.
4. **Canary é server-side weighted random** — sem state machine de rollout.
5. **Commit no SEU worktree**, `NÃO push`, `NÃO merge`.
6. **Estimativa**: 180-240min wall-clock por slice.
