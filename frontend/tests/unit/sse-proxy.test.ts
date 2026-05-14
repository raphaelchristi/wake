/**
 * Testa o route handler do proxy SSE (`/api/wake/sessions/[id]/stream`).
 * Cobre:
 *   - regex de sanitização (org/ws + session id)
 *   - injeção de tenant headers no upstream fetch
 *   - pipe da resposta com content-type SSE
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/wake/sessions/[id]/stream/route";

function makeRequest(url: string, headers: Record<string, string> = {}): {
  request: { url: string; headers: Headers; signal: AbortSignal };
  controller: AbortController;
} {
  const controller = new AbortController();
  return {
    request: { url, headers: new Headers(headers), signal: controller.signal },
    controller,
  };
}

const ORIGINAL_FETCH = globalThis.fetch;

describe("SSE proxy route", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_WAKE_API_BASE = "http://backend.test";
  });

  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    delete process.env.NEXT_PUBLIC_WAKE_API_BASE;
    delete process.env.WAKE_API_KEY;
  });

  it("rejects invalid org with 400", async () => {
    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=BadOrg!&ws=default",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/org/i);
  });

  it("rejects invalid ws with 400", async () => {
    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=default&ws=$$$",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/ws/i);
  });

  it("rejects org with CRLF injection", async () => {
    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=evil%0d%0aX-Inject%3a%20bad&ws=default",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    expect(res.status).toBe(400);
  });

  it("rejects invalid session id", async () => {
    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/bad%20id/stream?org=default&ws=default",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "bad id" }),
    });
    expect(res.status).toBe(400);
  });

  it("accepts good chars and injects tenant headers in upstream call", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response("data: hello\n\n", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_01HBCDEF/stream?org=acme&ws=prod-1",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_01HBCDEF" }),
    });

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toMatch(/text\/event-stream/);
    expect(fetchSpy).toHaveBeenCalledOnce();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const [upstreamUrl, init] = call;
    expect(String(upstreamUrl)).toBe(
      "http://backend.test/v1/sessions/sess_01HBCDEF/stream",
    );
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-Organization-Id"]).toBe("acme");
    expect(headers["X-Wake-Workspace-Id"]).toBe("prod-1");
  });

  it("forwards WAKE_API_KEY env var to upstream", async () => {
    process.env.WAKE_API_KEY = "server-side-key";
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response("", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=default&ws=default",
    );
    await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const headers = (call[1]?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-API-Key"]).toBe("server-side-key");
  });

  it("falls back to default/default when query params are omitted", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response("", {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream",
    );
    await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const headers = (call[1]?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-Organization-Id"]).toBe("default");
    expect(headers["X-Wake-Workspace-Id"]).toBe("default");
  });

  it("returns upstream status on non-2xx", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=default&ws=default",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    expect(res.status).toBe(404);
  });

  it("returns 502 when upstream throws", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;

    const { request } = makeRequest(
      "http://app.test/api/wake/sessions/sess_abc/stream?org=default&ws=default",
    );
    const res = await GET(request as never, {
      params: Promise.resolve({ id: "sess_abc" }),
    });
    expect(res.status).toBe(502);
  });
});
