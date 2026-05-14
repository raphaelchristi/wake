# Wake Python SDK (`wake-ai-client`)

Typed async-first client pra Wake API. Re-export de `wake.types` via OpenAPI codegen + retries com backoff em 5xx/429 + SSE streaming nativo.

> Publicado em PyPI como `wake-ai-client` (não confundir com `wake-ai`, o server package).

---

## Quickstart

### Install

```bash
pip install wake-ai-client
```

### Hello world

```python
import asyncio
from wake_ai_client import WakeClient

async def main():
    async with WakeClient(
        base_url="http://localhost:8080",
        api_key="dev",
        organization_id="acme",
        workspace_id="prod",
    ) as client:
        agent = await client.agents.list()
        print(f"{len(agent.data)} agents in workspace {client.workspace_id}")

asyncio.run(main())
```

### Auth resolution (precedence)

1. Args explícitos (`api_key="..."`)
2. Env var `WAKE_API_KEY`
3. **Raise** se nenhum encontrado e endpoint exige auth

```python
import os
os.environ["WAKE_API_KEY"] = "..."
client = WakeClient(base_url="http://localhost:8080")
```

### Headers injetados

| Header | Source |
|---|---|
| `X-Wake-API-Key` | `api_key` arg ou env |
| `X-Wake-Organization-Id` | `organization_id` arg (default `default`) |
| `X-Wake-Workspace-Id` | `workspace_id` arg (default `default`) |
| `X-Wake-User-Id` | `user_id` arg (opcional — só quando RBAC ON server-side) |

---

## API surface

### Sessions

```python
session = await client.sessions.create(agent_id="agent_abc")
print(session.id, session.status)

# Stream events (Server-Sent Events)
async for event in client.sessions.stream(session.id):
    print(event.type, event.payload)

# Append event
await client.sessions.append_event(
    session.id,
    type="user.message",
    payload={"text": "hello"},
    idempotency_key="msg-123",  # opt-in, dedupe via UNIQUE partial index
)

# List + filter
sessions = await client.sessions.list(
    status="running",
    agent_id="agent_abc",
    since="2026-05-01T00:00:00Z",
    page=1,
    page_size=50,
)

# Get + state snapshot
session = await client.sessions.get(session_id)
state = await client.sessions.state_at(session_id, seq=42)

# Lifecycle ops
await client.sessions.interrupt(session_id)
await client.sessions.archive(session_id)
await client.sessions.delete(session_id)
```

### Agents

```python
agent = await client.agents.create(
    name="My Agent",
    model={"id": "claude-opus-4-7"},
    system="You are a helpful assistant.",
    metadata={"max_cost_usd": "10.00"},  # Phase 7 cost budget
)

agents = await client.agents.list(include_archived=False)
versions = await client.agents.versions(agent.id)

agent = await client.agents.update(agent.id, system="Updated prompt")
await client.agents.archive(agent.id)
```

### Replay

```python
# Edit-and-replay (Phase 8)
new_session = await client.sessions.replay(
    original_session_id,
    system_prompt="Try this prompt instead",
    max_steps=10,
)
```

---

## Streaming details

`client.sessions.stream(id)` retorna `AsyncIterator[Event]`. Resilient a:

- Network blips: reconnect automático com `Last-Event-ID` (consome `seq` last received)
- Server restarts: backoff exponencial (1s → 2s → 4s → ... → 30s cap)
- Explicit close: `break` no loop chama `aclose()` no underlying SSE connection

```python
last_seq = 0
try:
    async for event in client.sessions.stream(session_id, since=last_seq):
        last_seq = event.seq
        handle(event)
        if event.type == "status" and event.payload.get("to") == "terminated":
            break
except KeyboardInterrupt:
    pass
```

---

## Retries

Default config:
- Retry em: 5xx + 429
- Max retries: 3
- Backoff: `min(2^n + jitter, 30s)`
- `Retry-After` honored (header de 429 + 503)

Override:
```python
client = WakeClient(
    base_url="http://localhost:8080",
    api_key="dev",
    max_retries=5,
    timeout=30.0,
)
```

Desabilitar retries:
```python
client = WakeClient(..., max_retries=0)
```

---

## Errors

| Exception | When |
|---|---|
| `WakeAPIError` (base) | HTTP error |
| `WakeAuthError` (401) | API key inválida ou ausente |
| `WakeForbiddenError` (403) | RBAC role insuficiente |
| `WakeNotFoundError` (404) | Resource não existe OU cross-workspace |
| `WakeRateLimitError` (429) | Rate-limit exceeded; `.retry_after` populado |
| `WakeServerError` (5xx) | Backend error após retries exhausted |
| `WakeStreamError` | SSE reconnect deu up |

Cada exception tem `.status_code`, `.detail`, `.request_id` (header `X-Wake-Request-Id` quando disponível).

---

## Idempotency

Append de eventos suporta `idempotency_key` opcional. Backend mantém UNIQUE partial index `(workspace_id, session_id, idempotency_key) WHERE idempotency_key IS NOT NULL` — retry com mesma key retorna evento existing.

```python
event = await client.sessions.append_event(
    session_id,
    type="user.message",
    payload={...},
    idempotency_key="client-generated-uuid",
)
# Re-call mesma chave → mesmo evento (sem nova row)
event_dup = await client.sessions.append_event(
    session_id,
    type="user.message",
    payload={"different": "value"},  # ignored
    idempotency_key="client-generated-uuid",
)
assert event.id == event_dup.id
```

---

## Examples

Ver `sdks/python/examples/` no repo.

## Development

```bash
cd sdks/python
pip install -e ".[dev]"
pytest
ruff check .
```
