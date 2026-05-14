# wake-ai-client — Python SDK for Wake AI

[![PyPI version](https://img.shields.io/pypi/v/wake-ai-client.svg)](https://pypi.org/project/wake-ai-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/wake-ai-client.svg)](https://pypi.org/project/wake-ai-client/)

The official **async-first Python SDK** for [Wake AI](https://wake.ai) — a
self-hosted runtime for production-grade AI agents. This client wraps the Wake
HTTP + SSE surface with typed pydantic models, retries, tenancy headers, and
streaming helpers, so you can ship in three lines of Python instead of writing
a fetch wrapper by hand.

> **Looking for the server?** That ships as the `wake-ai` package (or the
> `wake-ai/wake` Helm chart). This is the **client** — it is intended to be
> installed in your application, not on the Wake host.

---

## Table of contents

- [Install](#install)
- [Quickstart](#quickstart)
- [Authentication](#authentication)
- [Tenancy](#tenancy)
- [Sessions](#sessions)
- [Agents](#agents)
- [Events & content blocks](#events--content-blocks)
- [Streaming](#streaming)
- [Retries & error handling](#retries--error-handling)
- [Sync wrapper](#sync-wrapper)
- [Testing your code](#testing-your-code)
- [Versioning & compatibility](#versioning--compatibility)
- [License](#license)

---

## Install

```bash
pip install wake-ai-client
# or, with poetry:
poetry add wake-ai-client
# or, with uv:
uv add wake-ai-client
```

Python **3.11+** is required (the SDK uses modern union/type-hint syntax).

### Supported transports

* `httpx>=0.27` — async HTTP client (the SDK is async-first)
* `httpx-sse>=0.4` — Server-Sent Events parser
* `pydantic>=2.7` — typed wire shapes

You don't have to install these yourself: they are pinned as runtime
dependencies of `wake-ai-client`.

---

## Quickstart

```python
import asyncio
from wake_ai_client import WakeClient


async def main() -> None:
    async with WakeClient(
        base_url="https://wake.example.com",
        api_key="sk-wake-...",
        organization_id="org-acme",
        workspace_id="ws-default",
    ) as wake:
        # 1) Create an agent (or look one up by ID)
        agent = await wake.agents.create(
            name="researcher",
            model={"id": "claude-opus-4-7"},
            system="You are a helpful research assistant.",
        )

        # 2) Spin up a session
        session = await wake.sessions.create(agent_id=agent.id)

        # 3) Ask the agent something — appending a `user.message`
        #    event causes the dispatcher to kick the harness loop.
        await wake.sessions.append_event(
            session.id,
            type="user.message",
            payload={"text": "Summarize today's papers on LLM safety."},
        )

        # 4) Stream the response back in real time
        async for ev in wake.sessions.stream(session.id):
            if ev.type == "assistant.delta":
                print(ev.payload.get("text", ""), end="", flush=True)
            if ev.type == "assistant.message":
                break


asyncio.run(main())
```

That's the entire happy path. Read on for everything else.

---

## Authentication

The Wake API uses two mandatory headers:

| Header | Purpose |
| --- | --- |
| `X-Wake-API-Key` | The shared bearer credential, set on the Wake server via `WAKE_API_KEY`. |
| `X-Wake-Organization-Id` / `X-Wake-Workspace-Id` | Tenant scope. Mandatory in multi-tenant deployments; default to `"default"` for single-tenant. |

…and one optional header:

| Header | Purpose |
| --- | --- |
| `X-Wake-User-Id` | Principal identity, **required** when the Wake server runs with `WAKE_RBAC_ENABLED=true`. Used to evaluate role checks. |

You can wire these three ways:

### 1. Pass them explicitly (recommended)

```python
WakeClient(
    base_url="https://wake.example.com",
    api_key="sk-wake-...",
    organization_id="org-acme",
    workspace_id="ws-default",
    user_id="user-42",        # optional, only needed with RBAC
)
```

### 2. Fall back to `$WAKE_API_KEY`

If you omit `api_key=` entirely, the SDK reads the `WAKE_API_KEY` environment
variable. This is convenient for CLIs and CI jobs.

```bash
export WAKE_API_KEY=sk-wake-...
python my_script.py
```

```python
async with WakeClient(base_url="https://wake.example.com") as wake:
    ...  # api_key resolved from the env
```

### 3. Disable the key header entirely

If your Wake deployment runs without auth (local dev), pass `api_key=None`
explicitly. The header is then omitted from every request:

```python
WakeClient(base_url="http://localhost:8080", api_key=None)
```

---

## Tenancy

Wake is multi-tenant by design. **Every request** is scoped to an
`(organization, workspace)` pair, and the server enforces isolation: a session
created in workspace A is invisible to a client scoped to workspace B,
returning `404` rather than `403` (so cross-tenant probes leak nothing).

The client embeds the scope at construction time, so all subsequent calls
share it:

```python
acme = WakeClient(
    base_url="https://wake.example.com",
    api_key=API_KEY,
    organization_id="org-acme",
    workspace_id="ws-prod",
)

shadow = WakeClient(
    base_url="https://wake.example.com",
    api_key=API_KEY,
    organization_id="org-shadow",
    workspace_id="ws-eval",
)
# Two completely isolated views over the same Wake server.
```

The `default/default` scope keeps backwards compatibility with single-tenant
installs — no change required if you're not using tenants yet.

---

## Sessions

A session is a stateful conversation bound to a specific **agent version**.
Sessions hold their state machine (`idle → running → terminated`) and a
strictly-ordered event log.

### Create

```python
session = await wake.sessions.create(
    agent_id="agent_01H...",
    environment_id="env_01H...",   # optional
    metadata={"trace_id": "abc"},
    idempotency_key="caller-generated-uuid",  # optional, 24h window
)
```

The optional `idempotency_key` makes the call safe to retry — replays return
the previously-persisted session instead of creating a duplicate. See
[Phase 7](https://github.com/wake-ai/wake/blob/main/phases/PHASE-7-CONTRACT.md)
for the idempotency contract.

### List

```python
recent = await wake.sessions.list(page=1, page_size=50)
running = await wake.sessions.list(status="running")
matched = await wake.sessions.list(q="trace=abc")  # free-text search
```

The full filter surface mirrors `GET /v1/sessions` query params: `agent`,
`status`, `model`, `since`, `until`, `q`, `page`, `page_size`.

### Get / Delete / Interrupt / Archive

```python
session = await wake.sessions.get(session_id)
await wake.sessions.interrupt(session_id)    # graceful stop
await wake.sessions.archive(session_id)       # terminate + freeze
await wake.sessions.delete(session_id)        # hard delete (RBAC-gated)
```

`interrupt` and `archive` require `Role.ADMIN` or `Role.OPERATOR` when the
server runs with RBAC enabled.

---

## Agents

Agents are **versioned**. Every `update()` produces a new immutable version,
so prod sessions can pin to a stable version while you iterate.

```python
agent = await wake.agents.create(
    name="customer-support",
    model={"id": "claude-opus-4-7", "speed": "standard"},
    system="You are a customer support agent for Acme.",
    tools=[{"type": "bash"}, {"type": "file_read"}],
)

# Bump to a new version
agent_v2 = await wake.agents.update(agent.id, system="New prompt.")
assert agent_v2.version == agent.version + 1

# List historical versions (timeline)
versions = await wake.agents.list_versions(agent.id)

# Pin to a specific version when retrieving
v1 = await wake.agents.get(agent.id, version=1)
```

The dashboard's *Agent Versioning* UI uses the same surface, so anything you
build with the SDK round-trips through the human-facing tools as well.

---

## Events & content blocks

The Wake event log is the canonical record of a session. Every meaningful
moment lands as an `Event`:

| `type` | Meaning |
| --- | --- |
| `user.message` | A user-authored turn. Posting this kicks the dispatcher. |
| `assistant.message` | A full assistant turn (text + tool calls). |
| `assistant.delta` | A streamed chunk during generation. |
| `assistant.thinking` | Reasoning tokens (when extended thinking is on). |
| `tool_use` / `tool_result` | A model-issued tool call and its outcome. |
| `pause_turn` | The model paused awaiting external input. |
| `status` | State transition (e.g. `terminated`). |
| `error` | Harness or model failure. |
| `artifact` | A blob produced by the session (file, image). |
| `interrupt` | The user (or operator) requested a hard stop. |
| `provision` | Sandbox lifecycle. |
| `vault.access` | A secret was read. |

Append events:

```python
await wake.sessions.append_event(
    session.id,
    type="user.message",
    payload={"text": "Hello!"},
    metadata={"channel": "slack"},
    idempotency_key="msg-uuid-7",   # safe to retry
)
```

Pull events:

```python
events = await wake.sessions.list_events(session.id, since=0)
for ev in events:
    print(f"[{ev.seq}] {ev.type}")
```

### Extracting text

The `wake_ai_client.events` module ships small helpers for the common cases:

```python
from wake_ai_client.events import extract_text, is_terminal

async for ev in wake.sessions.stream(session.id):
    chunk = extract_text(ev)
    if chunk:
        print(chunk, end="")
    if is_terminal(ev):
        break
```

---

## Streaming

`client.sessions.stream(session_id)` returns an `AsyncIterator[Event]` that
yields events as they arrive. Heartbeat frames are filtered automatically; the
SDK keeps the underlying SSE connection alive and reconnects with
`Last-Event-ID` if the transport drops mid-stream:

```python
async for ev in wake.sessions.stream(session.id):
    if ev.type == "assistant.delta":
        print(ev.payload["text"], end="")
    elif ev.type == "assistant.message":
        break
```

Resumption knobs:

* `since=<int>` — start at this `seq`. The server replays any backlog above
  this watermark before going live.
* `last_event_id=<str>` — set the initial `Last-Event-ID` header. Useful
  after a previous run dropped on `evt_01H...`.

The SDK tracks the most recent event ID it observed and forwards it on
reconnect, so dropping a session and restarting the iterator is safe.

---

## Retries & error handling

Every error raised by the SDK derives from `WakeClientError`:

```python
from wake_ai_client import (
    WakeAuthError,        # 401/403
    WakeNotFoundError,    # 404
    WakeRateLimitError,   # 429 (carries .retry_after)
    WakeServerError,      # 5xx
    WakeAPIError,         # other HTTP errors
    WakeTransportError,   # connect/DNS/TLS/timeout
)

try:
    await wake.sessions.get("missing")
except WakeNotFoundError as exc:
    print(f"oops: {exc.detail}")
except WakeRateLimitError as exc:
    print(f"slow down — retry after {exc.retry_after}s")
except WakeAPIError as exc:
    print(f"HTTP {exc.status_code}: {exc.body}")
```

### Retry policy

| Verb | Default retries |
| --- | --- |
| `GET`, `DELETE`, `HEAD` | `max_retries` (default 3) |
| `POST`, `PATCH`, `PUT` | `0` — opt in per call |

Retries trigger on `429` and `5xx`. The SDK respects `Retry-After` when the
server provides it; otherwise it uses exponential backoff (`0.25s · 2^n`,
capped at 8s).

You can opt mutating verbs into retries when the call is idempotent (e.g. with
an `idempotency_key`):

```python
await wake.request("POST", "/v1/sessions", json=body, retries=3,
                   idempotency_key="caller-uuid")
```

To customize policy globally:

```python
WakeClient(base_url=..., api_key=..., max_retries=5, timeout=60.0)
```

---

## Sync wrapper

The SDK ships async-first because of SSE. If you only need request/response
calls and want a synchronous façade, wrap any coroutine with `asyncio.run`:

```python
import asyncio
from wake_ai_client import WakeClient


def list_sessions_sync(base_url: str, api_key: str) -> list:
    async def _go():
        async with WakeClient(base_url=base_url, api_key=api_key) as wake:
            return await wake.sessions.list()

    return asyncio.run(_go())
```

A first-party sync façade is on the roadmap (track issue
[#TBD](https://github.com/wake-ai/wake/issues)) — for now this two-liner keeps
the surface unambiguously single-threaded.

---

## Testing your code

The SDK accepts an `httpx.AsyncBaseTransport` for full request control. This
makes it trivial to unit-test your application without standing up a server:

```python
import httpx
from wake_ai_client import WakeClient


async def test_my_pipeline():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agents":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"detail": "not stubbed"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        api_key="test",
        transport=transport,
    ) as wake:
        agents = await wake.agents.list()
        assert agents == []
```

This is exactly how the SDK's own test suite (`pytest`) covers retries,
backoff, header injection, and SSE reconnection.

---

## Versioning & compatibility

`wake-ai-client` follows **SemVer**. The major version pins API compatibility:

* `0.x` — pre-1.0 stabilization. Breaking changes may land on minor bumps.
* `1.x` (future) — long-term stable Python surface.

Server compatibility:

| Client | Server |
| --- | --- |
| `0.1.x` | Wake `0.7.x` (Phase 7) + `0.8.x` (Phase 8) |

`pydantic` models use `extra="allow"`, so additive server changes never break
client deserialization — your version of the SDK keeps working through minor
server upgrades.

---

## License

Apache-2.0. See [LICENSE](./LICENSE).

---

## Where to next

* [Server docs](https://github.com/wake-ai/wake/tree/main/docs)
* [Event schema](https://github.com/wake-ai/wake/blob/main/docs/SPEC-EVENT-SCHEMA.md)
* [TypeScript SDK](../typescript/README.md)
* [`docs/SDK-PYTHON.md`](../../docs/SDK-PYTHON.md) — extended usage guide

Found a bug? Open an issue on the
[Wake repo](https://github.com/wake-ai/wake/issues) with the `sdk:python`
label, please.
