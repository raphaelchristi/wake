# Wake — Operations Guide (Phase 7)

> Como rodar Wake em produção sem queimar a confiança do primeiro
> customer. Cobre os três pilares do slice ops-throughput da Phase 7:
>
> 1. **Rate limiting** (slowapi + Redis opcional)
> 2. **Idempotency** (`metadata.idempotency_key` + UNIQUE partial index)
> 3. **Worker backpressure** (`X-Wake-Worker-Saturation` header + 503)
>
> Os outros dois pilares ops da Phase 7 — *cost-budget*/*retention* e
> *Prometheus*/*ServiceMonitor* — estão documentados em
> [`COST-BUDGET.md`](./COST-BUDGET.md), [`RETENTION.md`](./RETENTION.md),
> [`OBSERVABILITY.md`](./OBSERVABILITY.md) e [`BENCHMARKS.md`](./BENCHMARKS.md).

---

## TL;DR

| Feature | Default | Opt-out | Opt-in upgrade |
|---|---|---|---|
| Rate limit (writes) | 60/min por (api_key, workspace) | `WAKE_RATELIMIT_DISABLED=true` | `WAKE_RATELIMIT_WRITE=120/minute` |
| Rate limit (reads) | 300/min por (api_key, workspace) | idem | `WAKE_RATELIMIT_READ=600/minute` |
| Rate limit storage | in-memory (per-replica) | — | `WAKE_RATELIMIT_REDIS_URL=redis://...` (cross-replica) |
| Idempotency | inactive até o cliente mandar `idempotency_key` | sempre opt-in | — |
| Backpressure header | `X-Wake-Worker-Saturation` em toda resposta | `WAKE_BACKPRESSURE_DISABLED=true` | — |
| Backpressure 503 trigger | saturation >= 1.0 | mesma flag | `WAKE_BACKPRESSURE_THRESHOLD=0.85` (degrade earlier) |

---

## 1. Rate limiting

### Visão geral

Wake monta `slowapi` no app factory. O middleware é uma dependência de
todos os routers autenticados — `/health`, `/docs`, `/redoc`,
`/openapi.json` e `/metrics` ficam de fora porque são endpoints de
infraestrutura.

A chave do bucket é:

```
<sha256(api_key)[:16] | "anon">:<workspace_id>
```

ou seja:
- Cliente sem API key cai no bucket `anon:default` (todos compartilham).
- Cliente com API key e dois workspaces tem dois buckets separados.
- API key vaza? O storage (memory ou Redis) nunca tem a key em claro.

### Default limits

| Verb | Limit | Env override |
|---|---|---|
| POST · PUT · PATCH · DELETE | 60/minute | `WAKE_RATELIMIT_WRITE` |
| GET · HEAD (anything else)  | 300/minute | `WAKE_RATELIMIT_READ` |

Sintaxe do override segue [slowapi](https://slowapi.readthedocs.io):
`"<count>/<period>"`. `period` aceita `second`, `minute`, `hour`, `day`,
`month`, `year`.

### Storage backends

#### Memory (default)

In-process, per-replica. **Suficiente para single-replica deployments**
(POC, dev, single-pod Helm). Em deploys multi-replica o cliente pode
burlar o limite via round-robin no LB — cada réplica tem um contador
independente.

Sem configuração adicional necessária: `build_limiter()` defaults para
`MemoryStorage`.

#### Redis (opt-in)

Set `WAKE_RATELIMIT_REDIS_URL=redis://...` e o middleware passa a usar
`limits.aio.storage.RedisStorage` (subjacente do slowapi). Aceita:

- `redis://host:port/db`
- `rediss://host:port/db` (TLS)
- `redis+sentinel://host:port/master_name`

Wake **nunca hard-fails** se o Redis estiver inacessível: se a init
quebrar (driver `coredis` ausente p.ex.), o limiter cai pra memory com
um warning estruturado. Se a init der ok mas a primeira request quebrar
com timeout, `WakeRateLimiter.hit` engole a exception e libera a request
— degradação aberta em vez de fail-closed. Operadores devem alertar no
log key `ratelimit.storage_error_allowing_request`.

> **Warning** — Wake é uma plataforma multi-tenant. Memory backend em
> deploy multi-replica é um **footgun** porque o cliente pode burlar o
> limite via round-robin no LB. Em produção: **set
> `WAKE_RATELIMIT_REDIS_URL` ou use single-replica**.

### Response shape em 429

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{
  "detail": "rate limit exceeded: 60/minute",
  "limit":  "60/minute",
  "reset_at": 1715724803
}
```

- `Retry-After` é o número de segundos até o bucket resetar (igual à
  granularidade do limit; 60s para `*/minute`).
- `reset_at` é UNIX timestamp do reset esperado — clientes podem
  back-off determinístico (e.g. `sleep(reset_at - time.time())`).
- `limit` é o spec slowapi para o cliente registrar/diagnosticar.

### Per-route override

```python
from fastapi import Depends, APIRouter
from wake.api.ratelimit import rate_limit_dep

router = APIRouter(prefix="/v1/something")

@router.post(
    "/expensive",
    dependencies=[Depends(rate_limit_dep("5/minute", per_route=True))],
)
async def expensive_op(...): ...
```

`per_route=True` adiciona o request path ao bucket key, então essa rota
tem seu próprio contador independente do budget write global.

### Kill switch

`WAKE_RATELIMIT_DISABLED=true` desabilita o middleware inteiro. Útil
pra:

- Load test (k6) onde o operador quer medir capacidade bruta.
- Migration window quando o storage Redis está offline e o operador
  prefere indisponibilidade do limit ao 503 cascade.
- Dev mode.

---

## 2. Idempotency

### Visão geral

Worker double-process (Codex finding Phase 5.2) e retry naive de
clientes geram duplicate events: o mesmo `assistant.message` pode
aparecer 2× no log, drift no `seq`, custo dobrado em LiteLLM. A
solução é uma **idempotency key opcional** no event metadata + UNIQUE
partial index per `(workspace_id, session_id, idempotency_key)`.

### Como usar

#### Via API REST

```http
POST /v1/sessions/{session_id}/events
Content-Type: application/json
X-Wake-API-Key: ...
X-Wake-Workspace-Id: alpha

{
  "type": "user.message",
  "payload": { "content": [{"type": "text", "text": "hello"}] },
  "idempotency_key": "trace-xyz-attempt-1"
}
```

Repita a mesma request 5 vezes com o mesmo `idempotency_key` — Wake
retorna o mesmo event nos 5 responses. Apenas 1 row em `events`.

#### Via Python (EventStore direto)

```python
ev = await store.events.append(
    session_id="01HSESSION...",
    event_type="user.message",
    payload={"text": "hello"},
    idempotency_key="trace-xyz-attempt-1",
)
# Segunda chamada idêntica retorna o mesmo ev.
again = await store.events.append(
    session_id="01HSESSION...",
    event_type="user.message",
    payload={"text": "ignored"},
    idempotency_key="trace-xyz-attempt-1",
)
assert again.id == ev.id
assert again.seq == ev.seq
```

### Semântica

- `idempotency_key=None` (default) — comportamento histórico: cada
  `append` cria um novo row.
- `idempotency_key` set:
  - Primeira chamada: row novo, key mirrored em `metadata.idempotency_key`.
  - Subsequentes com mesma `(workspace, session, key)`: retorna o
    event existente. Payload da segunda chamada é descartado.
- `(workspace_id, session_id)` diferentes nunca colidem.
- Scope é per-session: a mesma key em duas sessions cria dois events
  independentes.
- TTL: **indefinido**. A retenção time-based (Phase 7 slice B) expira
  events velhos junto com as sessions, eliminando keys antigas
  automaticamente.

### Schema

#### SQLite (reference)

```sql
ALTER TABLE events ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_idempotency
  ON events (workspace_id, session_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

Wake instala o índice em `SQLiteStore.initialize()` automaticamente.
SQLite 3.8+ suporta partial indexes; nosso minimum é 3.35 (RETURNING),
muito acima.

#### Postgres

`adapters/postgres-store/alembic/versions/0004_idempotency.py`:

```sql
ALTER TABLE events ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
-- Per-partition (events é HASH-partitioned em session_id):
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_p_NN_idempotency
  ON events_p_NN (workspace_id, session_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

Per-partition porque PG só aceita UNIQUE index global em partitioned
tables se a partition key for prefix das colunas únicas — preferimos
per-partition + a invariante de que `HASH(session_id)` roteia toda
linha de uma session pra mesma partition.

### Race conditions

Postgres usa `pg_advisory_xact_lock(hashtext(session_id))` durante o
append. O segundo writer concorrente vê a row do primeiro commitada
antes de fazer seu próprio pre-check, então retorna o event existente
sem hit no UNIQUE index. Se chegar mesmo a hit:

- O `ON CONFLICT DO NOTHING` no INSERT (implementado via try/except no
  layer ORM) absorve o erro.
- Cliente recebe o event existente.

SQLite serializa via `asyncio.Lock` per-session no processo. Cross-process
seria um problema, mas Wake single-process SQLite é dev-only por
design.

### Migration runbook

```bash
# Postgres
cd adapters/postgres-store
alembic upgrade head

# Verify:
psql -c "SELECT idempotency_key FROM events LIMIT 0"
psql -c "\d+ events_p_00"  # should list uq_events_p_00_idempotency
```

Rollback:

```bash
alembic downgrade 0003_rbac
```

A migration é **idempotente** (`IF NOT EXISTS` everywhere) — re-running
em DB parcialmente migrado não quebra.

---

## 3. Worker backpressure

### Visão geral

O `SessionDispatcher` mantém um contador `in_flight` que sobe quando
`run_step` entra no adapter e desce no `finally`. `saturation()`
retorna `in_flight / max_in_flight` ∈ `[0.0, 1.0+)`.

O middleware `BackpressureMiddleware`:

1. Em toda response (não-exempta), adiciona o header
   `X-Wake-Worker-Saturation: 0.000–1.000+` (rounded 3 decimals).
2. Quando `saturation >= threshold` (default 1.0): rejeita a request
   com 503 + `Retry-After: 30`.

### Configuração

| Env | Default | Descrição |
|---|---|---|
| `WAKE_DISPATCHER_MAX_INFLIGHT` | 64 | Saturation ceiling. Subir aumenta paciência do dispatcher antes de retornar 503. |
| `WAKE_BACKPRESSURE_THRESHOLD` | 1.0 | Saturation que dispara 503. 0.85 = degrade earlier. |
| `WAKE_BACKPRESSURE_RETRY_AFTER` | 30 | Segundos retornados em `Retry-After` no 503. |
| `WAKE_BACKPRESSURE_DISABLED` | unset | `true` → middleware no-op (sem header, sem 503). |

### Response shape em 503

```http
HTTP/1.1 503 Service Unavailable
Retry-After: 30
X-Wake-Worker-Saturation: 1.000
Content-Type: application/json

{
  "detail": "worker pool saturated — retry later",
  "saturation": "1.000",
  "retry_after": 30
}
```

### Exempt paths

Endpoints de probe/infraestrutura **nunca** recebem 503 do middleware:

- `/health`
- `/docs`
- `/redoc`
- `/openapi.json`
- `/metrics` (futuro, slice C)

Isso garante que kubelet / Prometheus continuem funcionando mesmo com
o app saturado — fundamental pra autoscaler reagir.

### Como o cliente reage

SDKs Python/TS devem:

1. Ler `X-Wake-Worker-Saturation` em toda response 2xx e expor pra
   observability do caller (e.g. structlog field). Quando o valor passa
   de 0.7 sustentado, alertar capacity team.
2. Em 503 com `Retry-After`, fazer back-off + retry. Não é fatal — só
   indica que a capacidade está esgotada **agora**.
3. Quando o operator setou `WAKE_BACKPRESSURE_THRESHOLD=0.85`, o
   503 começa a chegar antes da saturação total. Use isso pra ramp up
   capacidade preemptivamente.

### Combinando com Kubernetes HPA

Phase 7 não entrega HPA template — adiado pra Phase 8+. Mas a métrica
está pronta pra ser consumida via Prometheus (slice C):

```promql
avg(wake_worker_saturation) by (pod) > 0.8
```

Quando essa expressão fica `1` sustentado, scale up.

---

## 4. Combined deployment recipes

### Single-replica dev

```bash
# .env
WAKE_RATELIMIT_DISABLED=true
WAKE_BACKPRESSURE_DISABLED=true
```

Sem rate-limit (libera load test), sem 503 (libera burst sessions),
sem dependência externa.

### Single-replica POC

```bash
WAKE_API_KEY=secret-key-123
WAKE_AUTH_REQUIRED=true
# Default limits (60/300 per minute, memory backend).
# Default backpressure (max_inflight=64, threshold=1.0).
```

Auth obrigatório, rate-limit memory backend (replica única, sem LB),
backpressure default.

### Multi-replica production

```bash
WAKE_API_KEY=secret-from-vault
WAKE_AUTH_REQUIRED=true
WAKE_RBAC_ENABLED=true
WAKE_RATELIMIT_REDIS_URL=rediss://redis-cluster.svc.local:6379/0
WAKE_RATELIMIT_WRITE=120/minute    # 2× default — production-tuned
WAKE_RATELIMIT_READ=600/minute     # 2× default
WAKE_DISPATCHER_MAX_INFLIGHT=128   # 2× default for bigger pod
WAKE_BACKPRESSURE_THRESHOLD=0.85   # degrade earlier, leave headroom
WAKE_BACKPRESSURE_RETRY_AFTER=15   # SDKs back-off faster
WAKE_PG_DSN=postgresql+asyncpg://...
```

### Helm overlay snippet

```yaml
# values-prod.yaml
env:
  WAKE_RATELIMIT_REDIS_URL:
    valueFrom:
      secretKeyRef:
        name: wake-redis
        key: url
  WAKE_RATELIMIT_WRITE: "120/minute"
  WAKE_RATELIMIT_READ:  "600/minute"
  WAKE_DISPATCHER_MAX_INFLIGHT: "128"
  WAKE_BACKPRESSURE_THRESHOLD:  "0.85"
  WAKE_BACKPRESSURE_RETRY_AFTER: "15"
```

---

## 5. Observability hooks

Slice C (metrics-benchmark) emite as métricas Prometheus
correspondentes. Sneak peek:

```
wake_ratelimit_hits_total{result="allowed|denied"}
wake_ratelimit_storage_errors_total
wake_worker_queue_depth (gauge)
wake_worker_saturation  (gauge)
wake_events_idempotent_dedupe_total
```

Use o dashboard JSON em `docs/OBSERVABILITY.md` (slice C) para
visualizar.

---

## 6. Runbooks

### Rate-limit storm

Sintoma: muitas 429 no log de um workspace específico.

1. `kubectl logs ... | grep ratelimit | grep <workspace_id>` —
   confirmar volume.
2. Bumpar o limite per-workspace via env override + restart (sticky:
   reset_at não é persistente):

   ```bash
   kubectl set env deploy/wake WAKE_RATELIMIT_WRITE=200/minute
   ```
3. Investigar se o cliente está respeitando `Retry-After`. Se não:
   ticket no SDK do customer.

### Redis lock-up

Sintoma: `ratelimit.storage_error_allowing_request` no log.

1. `redis-cli -u $WAKE_RATELIMIT_REDIS_URL ping` — confirmar.
2. Wake já degradou pra "allow everything" — sem ação urgente, mas
   sem rate-limit cross-replica. Restaurar Redis e o middleware
   retoma automatic.

### 503 storm

Sintoma: muitas 503 com `X-Wake-Worker-Saturation: 1.000+`.

1. Confirmar saturation via `/metrics` (slice C).
2. Scale up replicas: `kubectl scale deploy/wake --replicas=N+1`.
3. Médio prazo: tunar `WAKE_DISPATCHER_MAX_INFLIGHT` ou avaliar
   `WAKE_BACKPRESSURE_THRESHOLD` mais alto.

### Idempotency dedupe inesperado

Sintoma: cliente reporta "minha message não aparece" mas a request
retornou 202.

1. Inspect o event response — se `metadata.idempotency_key` está set,
   o cliente bateu key duplicada.
2. Investigar geração da key no cliente. Boas práticas:
   - UUID v4 per request.
   - Hash de (timestamp, payload) com salt.
   - **Nunca** key estática hardcoded.

---

## 7. Testes

```bash
# Unit (in-memory + SQLite):
pytest tests/unit/test_ratelimit.py tests/unit/test_idempotency.py tests/unit/test_backpressure.py -v

# Postgres (testcontainers; requer Docker):
pytest adapters/postgres-store/tests/test_idempotency.py -v
```

---

## 8. Rollback

| Feature | Rollback |
|---|---|
| Rate limit | `WAKE_RATELIMIT_DISABLED=true` + restart |
| Idempotency (PG) | `alembic downgrade 0003_rbac` |
| Idempotency (SQLite) | `DROP INDEX uq_events_idempotency; ALTER TABLE events DROP COLUMN idempotency_key` (manual; Wake não roda migrations no SQLite) |
| Backpressure | `WAKE_BACKPRESSURE_DISABLED=true` + restart |

A row column `idempotency_key` permanece em rows existentes mesmo no
rollback — só o índice cai. Re-aplicar a migração reusa as keys.

---

## 9. Decisões locked (de PHASE-7-CONTRACT)

- Rate limit lib: **slowapi** (FastAPI-native, MIT).
- Storage default: **in-memory**; Redis via env, fallback gracioso.
- Key: `<api_key_hash>:<workspace_id>`.
- Default limits: writes 60/min, reads 300/min.
- 429 carrega `Retry-After` + `{detail, limit, reset_at}`.
- Idempotency é per `(workspace_id, session_id, idempotency_key)`,
  TTL indefinido.
- Backpressure header: `X-Wake-Worker-Saturation`.
- 503 quando saturation >= threshold (default 1.0), `Retry-After: 30`.

---

## 10. Próximos passos

- Slice B (cost-budget + retention) — protege custo / storage long-term.
- Slice C (Prometheus + k6 benchmarks) — observability + capacidade
  comprovada.
- Phase 8+ — HPA template + per-customer billing aggregator.
