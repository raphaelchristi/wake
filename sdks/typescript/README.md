# @wake-ai/client

Official TypeScript SDK for the **Wake AI runtime** — a thin, dependency-free
wrapper around the public HTTP + SSE API. Works in browsers (modern), Node
(>=18), Deno, and Bun. The whole bundle weighs **under 30KB gzip** (currently
~3KB).

The shape mirrors the official Python SDK (`wake-ai-client`):

- `client.sessions.{create, list, get, delete, interrupt, archive, appendEvent, listEvents, stream}`
- `client.agents.{create, list, get, update, archive, listVersions}`
- A single `WakeClient` factory with retries, tenancy headers, and an env-var
  fallback for the API key.

> **Status:** `0.1.0` — pre-1.0. Wire format follows the Wake server but is
> not yet locked. Pin a minor version in production.

---

## Install

```bash
# pnpm
pnpm add @wake-ai/client

# npm
npm install @wake-ai/client

# yarn
yarn add @wake-ai/client

# bun
bun add @wake-ai/client
```

Requires `fetch` to be available globally. On Node ≥18 that's the default; on
older Nodes pass a polyfill via `options.fetch`.

---

## Quickstart

```ts
import { WakeClient } from "@wake-ai/client";

const wake = new WakeClient({
  baseUrl: "https://wake.example.com",
  apiKey: process.env.WAKE_API_KEY,
  organizationId: "org-acme",
  workspaceId: "ws-default",
});

// 1. Pick an agent
const [agent] = await wake.agents.list();

// 2. Open a session
const session = await wake.sessions.create({ agent_id: agent.id });

// 3. Append a user turn — the dispatcher kicks in automatically
await wake.sessions.appendEvent(session.id, {
  type: "user.message",
  payload: { text: "Summarize the README." },
});

// 4. Stream the assistant reply
for await (const event of wake.sessions.stream(session.id)) {
  if (event.type === "assistant.delta") {
    process.stdout.write(String(event.payload.text ?? ""));
  } else if (event.type === "assistant.message") {
    console.log("\n[done]", event.payload);
    break;
  }
}
```

---

## Authentication

| Mechanism | Header | Source |
|---|---|---|
| API key | `X-Wake-API-Key` | `apiKey` option, **or** `WAKE_API_KEY` env (Node only) |
| Organization | `X-Wake-Organization-Id` | `organizationId` option (default `"default"`) |
| Workspace | `X-Wake-Workspace-Id` | `workspaceId` option (default `"default"`) |
| User identity (RBAC) | `X-Wake-User-Id` | `userId` option (required when RBAC is on) |

```ts
// Explicit key
const wake = new WakeClient({ baseUrl, apiKey: "sk-wake-..." });

// Env fallback — only runs in Node
process.env.WAKE_API_KEY = "sk-wake-...";
const wake2 = new WakeClient({ baseUrl }); // picks up env var

// Disable the header entirely (e.g. for self-hosted dev clusters)
const wake3 = new WakeClient({ baseUrl, apiKey: null });
```

---

## Resources

### Sessions

```ts
const session = await wake.sessions.create({
  agent_id: "agent_01",
  environment_id: "env_default",
  metadata: { trace: "abc" },
});

await wake.sessions.list({
  agent: "agent_01",
  status: "running",
  since: new Date("2026-01-01"),
  page: 1,
  page_size: 25,
});

const s2 = await wake.sessions.get(session.id);
await wake.sessions.interrupt(session.id);
await wake.sessions.archive(session.id);
await wake.sessions.delete(session.id);
```

#### Events

```ts
// Append (server validates the type / payload shape per the Wake event schema)
await wake.sessions.appendEvent(
  session.id,
  { type: "user.message", payload: { text: "hi" } },
  { idempotencyKey: "req-123" } // optional 24h dedupe
);

// Paginated list of historical events
const events = await wake.sessions.listEvents(session.id, { since: 100 });
```

### Agents

```ts
const agent = await wake.agents.create({
  name: "researcher",
  model: { id: "claude-opus-4-7" },
  system: "You are a careful research assistant.",
  tools: [{ type: "web_search" }],
});

await wake.agents.list();
await wake.agents.get(agent.id, { version: 3 });        // pinned version
await wake.agents.update(agent.id, { system: "..." });  // bumps version
await wake.agents.listVersions(agent.id);
await wake.agents.archive(agent.id);
```

---

## Streaming

`client.sessions.stream(id)` returns an `AsyncIterableIterator<Event>` that:

1. Opens `GET /v1/sessions/{id}/stream` with `Accept: text/event-stream`.
2. Filters server-side `heartbeat` frames.
3. Reconnects on transport drops up to `maxReconnects` (default `5`).
4. Tracks the latest `id:` and forwards it as `Last-Event-ID` on reconnect, so
   the server can resume exactly where you left off.
5. 4xx errors (404, 401, …) surface as the normal `WakeAPIError` subclasses
   — they are **not** retried.

```ts
const ctrl = new AbortController();
setTimeout(() => ctrl.abort(), 30_000);

try {
  for await (const event of wake.sessions.stream(session.id, {
    signal: ctrl.signal,
    since: 0,          // mutually exclusive with lastEventId
    maxReconnects: 10, // override the default
  })) {
    handle(event);
  }
} catch (err) {
  if (err instanceof WakeTransportError) {
    // gave up after maxReconnects — present the user a "Reconnect" button
  } else {
    throw err;
  }
}
```

Breaking out of the loop or calling `iter.return()` cancels the underlying
`fetch` cleanly.

---

## Error model

Every error derives from `WakeClientError`:

```
WakeClientError
├── WakeTransportError      // network/fetch failure, retries exhausted
└── WakeAPIError            // HTTP non-2xx
    ├── WakeAuthError       // 401 / 403
    ├── WakeNotFoundError   // 404
    ├── WakeRateLimitError  // 429 (carries .retryAfter in ms)
    └── WakeServerError     // 5xx (only seen after retry exhaustion)
```

```ts
import {
  WakeAPIError,
  WakeAuthError,
  WakeRateLimitError,
  WakeTransportError,
} from "@wake-ai/client";

try {
  await wake.agents.list();
} catch (err) {
  if (err instanceof WakeAuthError) {
    // refresh the token, re-prompt for login, …
  } else if (err instanceof WakeRateLimitError) {
    await sleep(err.retryAfter ?? 5_000);
  } else if (err instanceof WakeAPIError) {
    console.error(`HTTP ${err.status}`, err.body);
  } else if (err instanceof WakeTransportError) {
    console.error("network issue:", err.message);
  } else {
    throw err;
  }
}
```

---

## Retries

Idempotent verbs (`GET`, `DELETE`, `HEAD`) retry up to `maxRetries` (default
`3`) on:

- `429 Too Many Requests` — honors `Retry-After` (seconds).
- `500 / 502 / 503 / 504` — exponential backoff (250 ms → 8 s cap).
- `fetch` rejections — same backoff.

Mutating verbs (`POST`, `PATCH`, `PUT`) **do not retry by default**. Opt in
per-call by setting `retries` on the `RequestOptions` and pairing the call
with an `idempotencyKey`:

```ts
await wake.sessions.appendEvent(
  session.id,
  { type: "user.message", payload: { text: "hi" } },
  { idempotencyKey: crypto.randomUUID() } // server dedupes for 24h
);
```

---

## Tenancy

The SDK sends three headers on every request — `X-Wake-Organization-Id`,
`X-Wake-Workspace-Id`, and (when supplied) `X-Wake-User-Id`. The server pins
all reads/writes to that tenant scope, so a leaking key cannot enumerate other
tenants.

```ts
const wake = new WakeClient({
  baseUrl,
  apiKey,
  organizationId: "org-acme",
  workspaceId: "ws-prod",
  userId: "alice@acme.com", // required when server RBAC is enabled
});
```

---

## Custom `fetch`

Drop-in replacements work — `undici.fetch`, `node-fetch`, `cross-fetch`, the
WHATWG fetch shipped with bundlers, etc.

```ts
import { fetch as undiciFetch, ProxyAgent } from "undici";

const agent = new ProxyAgent("http://corp-proxy:3128");
const wake = new WakeClient({
  baseUrl,
  fetch: (input, init) => undiciFetch(input, { ...init, dispatcher: agent }),
});
```

---

## Bundle size

The whole SDK ships as a single `dist/index.js` ESM file (plus a `.cjs`
mirror). Latest measurement against `tsup --minify`:

| Output | Raw | Gzip |
|---|---|---|
| ESM | 8.9 KB | 3.3 KB |
| CJS | 8.9 KB | 3.3 KB |

The 30 KB gzip ceiling in the project contract is enforced in CI.

---

## Stability + versioning

- **Wire types** mirror `src/wake/types.py` on the server. We add fields
  before we remove them — your `Event.payload` reads should always tolerate
  unknown keys.
- **`Event.type`** is a string union for ergonomics; new event types may land
  in minor versions and your code should handle the `default` branch.
- **Resource shapes** (`AgentConfig`, `Session`) gain optional fields without
  a major bump. Mandatory removals require a major bump.
- **SemVer** kicks in at `1.0.0`. Until then minor bumps may contain breaking
  changes; pin to a patch range (`~0.1.0`).

---

## Development

```bash
pnpm install
pnpm test         # vitest
pnpm typecheck    # tsc --noEmit
pnpm build        # tsup → dist/
```

Tests use a hand-rolled mock `fetch` (see `tests/helpers.ts`) — no `msw` or
`nock`, just plain `Response` objects.

---

## Releases

Tags matching `sdk-ts-v*` (e.g. `sdk-ts-v0.1.0`) trigger the
`sdk-typescript-ci` workflow to publish to npm. PRs only run lint + test +
build; nothing is published from non-tag refs.

---

## License

Apache-2.0.
