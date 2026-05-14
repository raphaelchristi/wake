/**
 * Shared test fixtures + a `fetch`-shaped mock used by the vitest suite.
 *
 * We rely on a hand-rolled mock instead of `msw` so the tests stay zero-dep.
 * The mock accepts a handler that receives the parsed `Request` and returns
 * either a `Response` or a `ReadableStream` body to simulate SSE.
 */

import type { AgentConfig, Event, Session } from "../src/types.js";

const now = () => new Date().toISOString();

export function sessionPayload(overrides: Partial<Session> = {}): Session {
  return {
    id: "sess_01",
    organization_id: "org-test",
    workspace_id: "ws-test",
    agent_id: "agent_01",
    agent_version: 1,
    status: "idle",
    metadata: {},
    created_at: now(),
    updated_at: now(),
    ...overrides,
  };
}

export function agentPayload(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    id: "agent_01",
    organization_id: "org-test",
    workspace_id: "ws-test",
    name: "test-agent",
    model: { id: "claude-opus-4-7", speed: "standard", provider: "anthropic" },
    tools: [],
    mcp_servers: [],
    skills: [],
    metadata: {},
    version: 1,
    created_at: now(),
    updated_at: now(),
    ...overrides,
  };
}

export function eventPayload(seq = 0, overrides: Partial<Event> = {}): Event {
  return {
    id: `evt_${String(seq).padStart(2, "0")}`,
    organization_id: "org-test",
    workspace_id: "ws-test",
    session_id: "sess_01",
    seq,
    type: "assistant.message",
    payload: { text: `hello ${seq}` },
    created_at: now(),
    ...overrides,
  };
}

export interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | null;
}

export type Handler = (req: RecordedRequest) => Response | Promise<Response>;

/**
 * Build a `fetch`-compatible mock + the array it records into.
 *
 * Usage:
 *
 * ```ts
 * const { fetch, recorded } = makeMockFetch(async (req) =>
 *   new Response(JSON.stringify({ data: [] }), { status: 200 }),
 * );
 * const client = new WakeClient({ baseUrl: "http://wake.test", fetch });
 * ```
 */
export function makeMockFetch(handler: Handler): {
  fetch: typeof fetch;
  recorded: RecordedRequest[];
} {
  const recorded: RecordedRequest[] = [];
  const mockFetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const headers: Record<string, string> = {};
    if (init.headers) {
      const h = new Headers(init.headers);
      h.forEach((v, k) => {
        headers[k.toLowerCase()] = v;
      });
    }
    const body = typeof init.body === "string" ? init.body : null;
    const req: RecordedRequest = {
      url,
      method: (init.method ?? "GET").toUpperCase(),
      headers,
      body,
    };
    recorded.push(req);
    return await handler(req);
  }) as typeof fetch;
  return { fetch: mockFetch, recorded };
}

/** Make an SSE `Response` body from a list of pre-formatted frame strings. */
export function sseResponse(frames: string[]): Response {
  const body = frames.join("");
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** Format one SSE frame matching the Wake server output. */
export function sseFrame(event: string, data: unknown, id?: string): string {
  const lines: string[] = [];
  if (id) lines.push(`id: ${id}`);
  lines.push(`event: ${event}`);
  lines.push(`data: ${JSON.stringify(data ?? {})}`);
  lines.push("");
  return lines.join("\n") + "\n";
}

/** Wrap a generator into a stream that emits frames with a controllable rhythm. */
export function streamingSSEResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** Make a `Response` whose body fails mid-stream — simulates a transport drop. */
export function brokenSSEResponse(framesBeforeDrop: string[]): Response {
  const encoder = new TextEncoder();
  let i = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < framesBeforeDrop.length) {
        controller.enqueue(encoder.encode(framesBeforeDrop[i]!));
        i += 1;
        return;
      }
      controller.error(new Error("transport drop"));
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}
