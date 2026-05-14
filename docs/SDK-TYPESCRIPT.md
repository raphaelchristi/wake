# Wake TypeScript SDK (`@wake-ai/client`)

Typed isomorphic client pra Wake API. Browser + Node compat via `fetch` + `EventSource` polyfill. Bundle <30KB gzip.

> Publicado em npm como `@wake-ai/client`.

---

## Install

```bash
npm install @wake-ai/client
# ou
pnpm add @wake-ai/client
# ou
yarn add @wake-ai/client
```

---

## Quickstart

```ts
import { WakeClient } from "@wake-ai/client";

const client = new WakeClient({
  baseUrl: "http://localhost:8080",
  apiKey: "dev",
  organizationId: "acme",
  workspaceId: "prod",
});

const session = await client.sessions.create({ agentId: "agent_abc" });
console.log(session.id, session.status);

// Stream events
for await (const event of client.sessions.stream(session.id)) {
  console.log(event.type, event.payload);
}
```

---

## Headers injetados

| Header | Source |
|---|---|
| `X-Wake-API-Key` | `apiKey` config ou `WAKE_API_KEY` env (Node only) |
| `X-Wake-Organization-Id` | `organizationId` (default `default`) |
| `X-Wake-Workspace-Id` | `workspaceId` (default `default`) |
| `X-Wake-User-Id` | `userId` opt (Phase 8+ RBAC) |

---

## API surface

### Sessions

```ts
// CRUD
const session = await client.sessions.create({ agentId: "agent_abc" });
const session2 = await client.sessions.get(sessionId);
const list = await client.sessions.list({ status: "running", pageSize: 50 });
await client.sessions.delete(sessionId);

// Append + stream
await client.sessions.appendEvent(sessionId, {
  type: "user.message",
  payload: { text: "hello" },
  idempotencyKey: "msg-123",
});

for await (const event of client.sessions.stream(sessionId)) {
  // ...
}

// Lifecycle
await client.sessions.interrupt(sessionId);
await client.sessions.archive(sessionId);
const state = await client.sessions.stateAt(sessionId, 42);
```

### Agents

```ts
const agent = await client.agents.create({
  name: "My Agent",
  model: { id: "claude-opus-4-7" },
  system: "You are a helpful assistant.",
  metadata: { max_cost_usd: "10.00" },
});

const agents = await client.agents.list({ includeArchived: false });
const versions = await client.agents.versions(agent.id);

await client.agents.update(agent.id, { system: "..." });
await client.agents.archive(agent.id);
```

### Replay (Phase 8)

```ts
const newSession = await client.sessions.replay(originalId, {
  systemPrompt: "Try this instead",
  maxSteps: 10,
});
```

---

## Streaming

`client.sessions.stream()` retorna `AsyncIterableIterator<Event>`. Browser usa `EventSource` (com `?` query string fallback porque EventSource não aceita headers); Node usa `fetch` + `ReadableStream`.

Resilient:
- Reconnect automático com `Last-Event-ID`
- Backoff exponencial (1s → 30s)
- Cancel via `break` no for-await ou abort signal

```ts
const controller = new AbortController();
setTimeout(() => controller.abort(), 30_000); // 30s timeout

try {
  for await (const event of client.sessions.stream(sessionId, { signal: controller.signal })) {
    if (event.type === "status" && event.payload.to === "terminated") break;
    handle(event);
  }
} catch (err) {
  if (err.name !== "AbortError") throw err;
}
```

---

## Retries

Default:
- Retry em 5xx + 429
- Max: 3
- Backoff: exponential com jitter
- `Retry-After` honored

```ts
const client = new WakeClient({
  baseUrl: "...",
  apiKey: "...",
  maxRetries: 5,
  timeout: 30_000,
});
```

---

## Errors

```ts
import {
  WakeApiError,
  WakeAuthError,
  WakeForbiddenError,
  WakeNotFoundError,
  WakeRateLimitError,
  WakeServerError,
  WakeStreamError,
} from "@wake-ai/client";

try {
  await client.sessions.create({ agentId: "..." });
} catch (err) {
  if (err instanceof WakeRateLimitError) {
    console.log(`retry after ${err.retryAfter}s`);
  } else if (err instanceof WakeNotFoundError) {
    console.log("agent not found (or cross-workspace)");
  } else throw err;
}
```

---

## Browser usage

Funciona out-of-the-box em browsers modernos com `fetch` + `EventSource`. Pra projetos que precisam de polyfill, instalar `event-source-polyfill`.

```ts
// SvelteKit, Next.js, React, Vue, etc:
import { WakeClient } from "@wake-ai/client";

export const client = new WakeClient({
  baseUrl: import.meta.env.VITE_WAKE_URL,
  apiKey: import.meta.env.VITE_WAKE_API_KEY,
});
```

⚠️ **Não expose API key em código cliente.** Use Next.js API routes / SvelteKit endpoints / etc. pra proxy.

---

## Node usage

```ts
import { WakeClient } from "@wake-ai/client";

const client = new WakeClient({
  baseUrl: process.env.WAKE_URL,
  apiKey: process.env.WAKE_API_KEY,
});
```

Funciona em Node 20+ (fetch nativo). Pra Node 18 ou anterior, instalar `undici` global.

---

## Idempotency

```ts
const ev = await client.sessions.appendEvent(sessionId, {
  type: "user.message",
  payload: { text: "..." },
  idempotencyKey: crypto.randomUUID(),
});
// Re-call retorna evento existing — não cria duplicate.
```

---

## Development

```bash
cd sdks/typescript
pnpm install
pnpm typecheck
pnpm vitest run
pnpm build  # tsup, gera dist/index.{cjs,js,d.ts}
```

Bundle target: <30KB gzip. CI check em `.github/workflows/sdk-typescript-ci.yml`.
