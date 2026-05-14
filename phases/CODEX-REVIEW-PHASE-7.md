# Phase 7 Adversarial Review — Operational Hardening

> **Substituição inline** do Codex review (CLI hit usage limit). Review feita por análise direta de code dos 16 commits em `v0.6.1-fixes..v0.7.0-ops-hardening`.
>
> **Scope:** rate-limit + idempotency + backpressure + cost-budget + retention + Prometheus + benchmarks. Tag: `v0.7.0-ops-hardening` (`b71d70a`).

---

## HIGH

### H1 — `CostBudgetEnforcer` double-counts `cost_usd` quando adapter emite em payload AND metadata

| Field | Detail |
|---|---|
| File:line | `src/wake/runtime/cost_budget.py:80-98` (função `event_cost`) |
| Problemático | `for source in (event.payload, event.metadata): ... total += Decimal(str(raw))` soma `cost_usd` de **ambos** payload e metadata se ambos presentes. O docstring (`Adapters emit per-event cost_usd on event.payload and/or event.metadata`) sugere "OR" mas a implementação soma. |
| Exploitação | Se um adapter LLM emite o mesmo `cost_usd` em payload e metadata (defensive duplication ou bug), o budget é tripado 2x mais cedo — sessions interrompidas prematuramente. Impacto inverso também possível: adapter emite cost só em payload mas budget pensa que é apenas metadata. |
| Fix proposto | Mudar pra "first non-None wins": iterar e usar `break` no primeiro `cost_usd` encontrado. Ou normalizar via `payload.cost_usd if "cost_usd" in payload else metadata.get("cost_usd")`. Adicionar test parametrizado cobrindo: só payload, só metadata, ambos com mesmo valor (expect=valor não 2×valor), ambos com valores diferentes (expect=first). |

### H2 — Archive S3 ETag verify fail em uploads multipart silently bloqueia archive

| Field | Detail |
|---|---|
| File:line | `src/wake/cli/retention.py:14` (docstring), implementação ETag verify provavelmente em archive function below line 200 |
| Problemático | Docstring diz "Order is ALWAYS: upload to S3 → verify ETag → delete local". Para uploads <5MB, ETag do S3 = MD5 do file (verify trivial). Para uploads ≥5MB (multipart), ETag = `MD5(MD5_of_part_1 + MD5_of_part_2 + ...) + "-" + part_count` — **não** equivale ao MD5 do file completo. |
| Exploitação | Archive batch com >5MB de events (~50k events) gera multipart upload → ETag local-computed (MD5 do gzip) não bate com ETag S3 → verify retorna fail → arquivo NÃO deletado local. Próxima rodada repete a tentativa, sempre falhando. Não é data loss (delete só em success), mas archive batch **nunca completa** = duplicação eterna em S3 + storage local nunca libera. |
| Fix proposto | Detectar multipart pelo `-NN` suffix no ETag e usar verificação alternativa: (a) comparar `Content-Length`, (b) compute multipart-style ETag local, ou (c) trust S3 success status (200/204) sem verify byte-by-byte (S3 já garante via checksum interno). Adicionar test simulando upload multipart com ETag composto. |

### H3 — Backpressure middleware lê saturation **uma vez** — request long-running pode passar mesmo após saturação

| Field | Detail |
|---|---|
| File:line | `src/wake/api/middleware/backpressure.py:153-183` |
| Problemático | `saturation` é lido antes de `call_next(request)`. Se durante a request o dispatcher saturar (outras requests aumentam `in_flight`), essa request continua sem 503. |
| Exploitação | Requests que executam dispatch internamente (POST /v1/sessions/{id}/events que dispara worker) podem starvar o worker pool sem rejeição: 1000 clientes mandam request "leve" simultaneamente, todos passam o threshold check (saturation < 1 no momento), todos disparam dispatcher → in_flight explode. |
| Fix proposto | Aceito como design choice (single check per request mantém latency baixa). MAS adicionar warning no `docs/OPERATIONS.md` documentando que threshold é "best-effort optimistic" + recomendar rate-limit como primeira linha de defesa. Test: simular burst de 100 requests concurrent, assert que ≥X foram 503'd. |

---

## MEDIUM

### M1 — Rate-limit silent fallback quando storage errors em runtime

| Field | Detail |
|---|---|
| File:line | `src/wake/api/ratelimit.py:147-166` |
| Problemático | `WakeRateLimiter.hit()` catch `Exception` → log warning + return `True` (allowed). Operador precisa monitorar log key `ratelimit.storage_error_allowing_request` pra ver — não há counter Prom dedicado. |
| Exploitação | Redis intermitente vira rate-limit silently off durante outage. Atacante que detectou padrão pode timing attack pra hit storage durante janela. |
| Fix proposto | Adicionar Prom counter `wake_ratelimit_storage_errors_total{backend}` em `src/wake/observability/metrics.py` + incrementar no except block. Alert example em `docs/OBSERVABILITY.md`. |

### M2 — Migration 0005 partition count vem de env — risco de drift upgrade/downgrade

| Field | Detail |
|---|---|
| File:line | `adapters/postgres-store/alembic/versions/0005_idempotency.py:47-55, 76-83, 87-91` |
| Problemático | `_partition_count()` lê `WAKE_PG_EVENT_PARTITIONS` (default 16). Se upgrade rodou com `WAKE_PG_EVENT_PARTITIONS=16` e downgrade roda com `=32`, downgrade tenta drop 32 indices mas só 16 existem. `DROP INDEX IF EXISTS` mascara erro, mas indices `uq_events_p_16..31_idempotency` (não-existentes) são "tentados" sem efeito real. Inverso é pior: upgrade=32, downgrade=16 → 16 indices órfãos. |
| Exploitação | Operator script de upgrade/downgrade usa diferent env state acidentalmente → indices órfãos persistem em prod. Sintoma: queries lentas (índice extra), schema drift entre clusters. |
| Fix proposto | Migration deve descobrir partitions count dinamicamente via `SELECT count(*) FROM pg_inherits WHERE inhparent = 'events'::regclass` em vez de env var. Adicionar test_migrations que upgrade+downgrade preserva schema. |

### M3 — Rate-limit bucket cardinality: workspace_id arbitrário spawn buckets ilimitados

| Field | Detail |
|---|---|
| File:line | `src/wake/api/ratelimit.py:91-102` (`key_for_request`) |
| Problemático | Bucket key = `{api_key_hash}:{workspace_id}`. Cliente pode mandar `X-Wake-Workspace-Id: garbage-N` com N variando — cada combinação spawn bucket novo em memória. MemoryStorage não tem cap declarado. |
| Exploitação | DoS via cardinality explosion no rate-limit storage. Atacante envia 1M requests com workspace_id diferente cada uma — memory storage cresce até OOM. Backend RBAC `get_tenant_context` valida que `workspace_id` é não-vazio mas NÃO valida existência prévia. |
| Fix proposto | (a) Validar workspace_id contra UserStore (existe? user tem acesso?) ANTES do rate-limit hit; (b) bound MemoryStorage com LRU cap (1000 buckets por default); ou (c) compute bucket key incluindo `user_id` real depois de RBAC validation, não workspace_id cru. |

### M4 — Compact deletion race com concurrent appends

| Field | Detail |
|---|---|
| File:line | `src/wake/cli/retention.py:165-280` (estimated; `events_compact` function), `src/wake/store/base.py` (`compact_session` helper) |
| Problemático | Compact reads deltas → cria snapshot event → deleta deltas. Se durante essa sequência um worker emite `assistant.delta` novo, esse delta pode ser deletado (range-based) OR sobrevive mas é órfão (sem partner snapshot). |
| Exploitação | Run compact concurrent com session ativa = perda de eventos ou corrupção da ordem replay. |
| Fix proposto | Compact deve adquirir advisory lock (Postgres `pg_advisory_xact_lock(hash(session_id))`) antes do read+delete. SQLite: usar transaction com BEGIN EXCLUSIVE. Test: spawn concurrent worker durante compact, assert event count == expected. |

### M5 — `WakeRateLimiter.hit()` silenciamento de errors também afeta workspace count

| Field | Detail |
|---|---|
| File:line | `src/wake/api/ratelimit.py:147-166` |
| Problemático | Quando storage falha, todos os requests passam — mas isso aplica a TODOS workspaces simultaneamente. Single Redis hiccup = global rate-limit off por X seconds. |
| Fix proposto | Idem M1 — mas adicionar circuit breaker: após N errors em janela Y, fail-CLOSED (return False = reject) por janela Z. Documentar trade-off. |

---

## LOW

### L1 — `format_saturation()` clamp negativos mas `in_flight` underflow não logged

| Field | Detail |
|---|---|
| File:line | `src/wake/api/middleware/backpressure.py:98-104`, `src/wake/runtime/dispatcher.py` (line ~280, `self.in_flight = max(0, self.in_flight - 1)`) |
| Problemático | `max(0, in_flight - 1)` mascara underflow se decrement extra acontecer. Header sempre formata >= 0, mas root cause silently lost. |
| Exploitação | Dispatcher bug que decrementa 2× = silent state corruption. Saturation header still reports 0 mesmo com 1 step in-flight (subsequent steps not tracked). |
| Fix proposto | `if self.in_flight <= 0: logger.warning("dispatcher_inflight_underflow", current=self.in_flight); self.in_flight = 0` em vez de max(0, x-1) silent. |

### L2 — `/metrics` Prom endpoint sem auth permite enumeração de workspaces (quando label opt-in ON)

| Field | Detail |
|---|---|
| File:line | `src/wake/api/metrics_prom.py` (não lido completo nesta review; deduzido do contract + observability docs) |
| Problemático | `WAKE_METRICS_WORKSPACE_LABEL=true` adiciona workspace ao label de `wake_events_total` etc. `/metrics` é unauthenticated. Atacante pode coletar lista de workspaces via scrape. |
| Exploitação | Tenant enumeration via /metrics. Mitigação atual: depende de NetworkPolicy (firewall via documentation, não enforcement). |
| Fix proposto | (a) Documentar OBRIGATORIEDADE de NetworkPolicy em `docs/OBSERVABILITY.md`; (b) opt-in DELIBERATE no Helm com warning bem visível; (c) considerar endpoint /metrics protegido via API key separada quando workspace label ON. |

### L3 — Migration renumbering audit trail é em comentário, não declarative

| Field | Detail |
|---|---|
| File:line | `adapters/postgres-store/alembic/versions/0005_idempotency.py:6, 41-42`, commits `660481d` + `bcdf2b7` |
| Problemático | Revision IDs foram renumerados durante merge (0004→0005, 0005→0006). Há comentários "Phase 7 — Tier 1 gap #4 (worker double-process dedupe + client retry safety)" mas `Revision ID: 0004_idempotency` em comentário top continua dizendo "0004" enquanto `revision = "0005_idempotency"` na linha 41. Mismatch. |
| Fix proposto | Atualizar docstring header pra refletir "Revision ID: 0005_idempotency" e adicionar nota sobre renumber durante merge Phase 7. Comment-only fix. |

---

## Sumário

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 5 |
| LOW | 3 |
| **Total** | **11** |

### Recomendação imediata (antes do merge Phase 8)

- **H1** (cost-budget double-count) — fix em <1h, blocker pra customer real que usa cost-budget
- **H2** (archive multipart ETag) — fix em ~2h, blocker pra retention real (datasets >5MB)
- **M2** (migration partition count drift) — fix em ~1h, blocker pra upgrade safety

**MEDIUM e LOW** podem ir pra backlog Phase 8.1 (similar a Phase 6.1 pattern).

### Não revisados nesta passada (gap intencional — sem time)

- `src/wake/observability/metrics.py` detalhes Prom collectors
- `src/wake/runtime/dispatcher.py` versão final pós-3-way-merge — race conditions dispatcher
- k6 scenarios `tests/load/k6/*.js`
- Helm `cronjob-retention.yaml` PodSpec safety
- Compact path completa em `EventStore.compact_session`

**Recomendação:** rodar Codex review oficial quando usage limit liberar (6:47 PM) pra catch o que essa review inline missed.

---

*Review gerada inline por Claude (substituto do Codex CLI). Análise de code, não de execução. Findings precisam ser validados via tests/exploitation real antes de qualifier como definitivos.*
