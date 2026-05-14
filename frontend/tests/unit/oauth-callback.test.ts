/**
 * Testa o route handler do OAuth callback proxy
 * (`POST /oauth/callback/api`).
 *
 * Foco principal (Codex review HIGH #2 — Phase 6 fixes):
 *   - O proxy NÃO pode forwardar `X-Wake-API-Key` enviado pelo cliente.
 *     A única origem de auth aceita é `process.env.WAKE_API_KEY`.
 *   - O proxy NÃO pode forwardar `X-Wake-User-Id` enviado pelo cliente.
 *     Aceitar esse header equivale a header spoofing do RBAC principal.
 *   - Tenancy (org/ws) e bypass de input continuam validados.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/oauth/callback/api/route";

function makeRequest(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): { url: string; headers: Headers; json: () => Promise<unknown> } {
  return {
    url,
    headers: new Headers(headers),
    json: async () => body,
  };
}

const ORIGINAL_FETCH = globalThis.fetch;

describe("OAuth callback proxy route", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_WAKE_API_BASE = "http://backend.test";
  });

  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
    delete process.env.NEXT_PUBLIC_WAKE_API_BASE;
    delete process.env.WAKE_API_KEY;
  });

  it("rejects invalid json body with 400", async () => {
    const req = {
      url: "http://app.test/oauth/callback/api",
      headers: new Headers(),
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Parameters<typeof POST>[0];
    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("rejects body missing 'code' or 'state'", async () => {
    const req = makeRequest("http://app.test/oauth/callback/api", { code: "x" });
    const res = await POST(req as unknown as Parameters<typeof POST>[0]);
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/code|state/);
  });

  it("rejects invalid org tenant with 400", async () => {
    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "abc", state: "xyz" },
      { "x-wake-organization-id": "Bad Org!" },
    );
    const res = await POST(req as unknown as Parameters<typeof POST>[0]);
    expect(res.status).toBe(400);
  });

  it("forwards tenant headers + server-side WAKE_API_KEY upstream", async () => {
    process.env.WAKE_API_KEY = "server-only-key";
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api?org=acme&ws=prod-1",
      { code: "code-abc", state: "state-xyz" },
    );
    const res = await POST(req as unknown as Parameters<typeof POST>[0]);
    expect(res.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledOnce();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const [upstreamUrl, init] = call;
    expect(String(upstreamUrl)).toContain(
      "http://backend.test/v1/vault/oauth/callback",
    );
    expect(String(upstreamUrl)).toContain("code=code-abc");
    expect(String(upstreamUrl)).toContain("state=state-xyz");
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-Organization-Id"]).toBe("acme");
    expect(headers["X-Wake-Workspace-Id"]).toBe("prod-1");
    expect(headers["X-Wake-API-Key"]).toBe("server-only-key");
  });

  // Regressão: Codex review HIGH #2 — proxy NUNCA pode aceitar
  // `X-Wake-API-Key` vindo do request do cliente.
  it("ignores client-supplied X-Wake-API-Key (no header forwarded)", async () => {
    delete process.env.WAKE_API_KEY;
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "code-abc", state: "state-xyz" },
      { "x-wake-api-key": "attacker-supplied-key" },
    );
    await POST(req as unknown as Parameters<typeof POST>[0]);
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const headers = (call[1]?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-API-Key"]).toBeUndefined();
    expect(Object.values(headers)).not.toContain("attacker-supplied-key");
  });

  it("client-supplied X-Wake-API-Key cannot override server WAKE_API_KEY", async () => {
    process.env.WAKE_API_KEY = "real-server-key";
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "code-abc", state: "state-xyz" },
      { "x-wake-api-key": "attacker-supplied-key" },
    );
    await POST(req as unknown as Parameters<typeof POST>[0]);
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const headers = (call[1]?.headers ?? {}) as Record<string, string>;
    // Server-side é a ÚNICA origem aceita.
    expect(headers["X-Wake-API-Key"]).toBe("real-server-key");
    expect(Object.values(headers)).not.toContain("attacker-supplied-key");
  });

  it("ignores client-supplied X-Wake-User-Id (no RBAC principal spoofing)", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    globalThis.fetch = fetchSpy as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "code-abc", state: "state-xyz" },
      { "x-wake-user-id": "admin-alice" },
    );
    await POST(req as unknown as Parameters<typeof POST>[0]);
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("fetch was not called");
    const headers = (call[1]?.headers ?? {}) as Record<string, string>;
    expect(headers["X-Wake-User-Id"]).toBeUndefined();
    expect(Object.values(headers)).not.toContain("admin-alice");
  });

  it("returns upstream status with detail on backend error", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: "state expired" }), {
        status: 400,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "code-abc", state: "state-xyz" },
    );
    const res = await POST(req as unknown as Parameters<typeof POST>[0]);
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/state expired/);
  });

  it("returns 502 when upstream throws", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;

    const req = makeRequest(
      "http://app.test/oauth/callback/api",
      { code: "code-abc", state: "state-xyz" },
    );
    const res = await POST(req as unknown as Parameters<typeof POST>[0]);
    expect(res.status).toBe(502);
  });
});
