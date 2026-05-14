import { beforeEach, describe, expect, it, vi } from "vitest";

import { WakeApiClient, WakeApiError } from "@/lib/api/client";
import { setApiKey } from "@/lib/auth";
import { setTenantScope } from "@/lib/tenant";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function headersFromCall(call: Parameters<typeof fetch>[1]): Headers {
  const init = call as RequestInit | undefined;
  return (init?.headers ?? new Headers()) as Headers;
}

describe("WakeApiClient", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("sends the X-Wake-API-Key header when an API key is set", async () => {
    setApiKey("wake_test_abc");
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions();
    expect(fetchSpy).toHaveBeenCalledOnce();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const init = call[1] as RequestInit | undefined;
    const headers = (init?.headers ?? new Headers()) as Headers;
    expect(headers.get("X-Wake-API-Key")).toBe("wake_test_abc");
  });

  it("sends tenancy headers with default/default when nothing is persisted", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const headers = headersFromCall(call[1]);
    expect(headers.get("X-Wake-Organization-Id")).toBe("default");
    expect(headers.get("X-Wake-Workspace-Id")).toBe("default");
  });

  it("sends tenancy headers using the persisted scope", async () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const headers = headersFromCall(call[1]);
    expect(headers.get("X-Wake-Organization-Id")).toBe("acme");
    expect(headers.get("X-Wake-Workspace-Id")).toBe("prod");
  });

  it("supports tenantScope override (for SSR / testes)", async () => {
    setTenantScope({ organizationId: "acme", workspaceId: "prod" });
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({
      fetchImpl: fetchSpy,
      tenantScope: { organizationId: "override", workspaceId: "scope" },
    });
    await client.listSessions();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const headers = headersFromCall(call[1]);
    expect(headers.get("X-Wake-Organization-Id")).toBe("override");
    expect(headers.get("X-Wake-Workspace-Id")).toBe("scope");
  });

  it("re-reads tenant scope per request (no cached snapshot)", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions();
    setTenantScope({ organizationId: "next", workspaceId: "tenant" });
    await client.listSessions();
    const calls = fetchSpy.mock.calls;
    if (calls.length < 2) throw new Error("expected two fetch calls");
    expect(headersFromCall(calls[0]?.[1]).get("X-Wake-Organization-Id")).toBe("default");
    expect(headersFromCall(calls[1]?.[1]).get("X-Wake-Organization-Id")).toBe("next");
    expect(headersFromCall(calls[1]?.[1]).get("X-Wake-Workspace-Id")).toBe("tenant");
  });

  it("omits the auth header when no key is set", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const init = call[1] as RequestInit | undefined;
    const headers = (init?.headers ?? new Headers()) as Headers;
    expect(headers.get("X-Wake-API-Key")).toBeNull();
  });

  it("supports an explicit apiKey override (e.g. for SSR)", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy, apiKey: "wake_override" });
    await client.listSessions();
    const call = fetchSpy.mock.calls[0];
    if (!call) throw new Error("expected fetch to be called");
    const init = call[1] as RequestInit | undefined;
    const headers = (init?.headers ?? new Headers()) as Headers;
    expect(headers.get("X-Wake-API-Key")).toBe("wake_override");
  });

  it("encodes session filters into query params", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await client.listSessions({
      agent: "agent_xyz",
      status: "running",
      model: "claude-opus-4-7",
      since: "2026-01-01T00:00:00Z",
      page: 2,
      page_size: 25,
    });
    const call0 = fetchSpy.mock.calls[0];
    if (!call0) throw new Error("expected fetch to be called");
    const url = new URL(call0[0] as string);
    expect(url.pathname).toBe("/v1/sessions");
    expect(url.searchParams.get("agent")).toBe("agent_xyz");
    expect(url.searchParams.get("status")).toBe("running");
    expect(url.searchParams.get("model")).toBe("claude-opus-4-7");
    expect(url.searchParams.get("since")).toBe("2026-01-01T00:00:00Z");
    expect(url.searchParams.get("page")).toBe("2");
    expect(url.searchParams.get("page_size")).toBe("25");
  });

  it("throws WakeApiError on non-2xx responses with parsed detail", async () => {
    const fetchSpy = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ detail: "session not found" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    let caught: unknown;
    try {
      await client.getSession("missing");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(WakeApiError);
    const err = caught as WakeApiError;
    expect(err.status).toBe(404);
    expect(err.isAuthError).toBe(false);
    expect(err.message).toContain("session not found");
  });

  it("marks 401/403 as auth errors", async () => {
    const fetchSpy = vi.fn<typeof fetch>(
      async () =>
        new Response(JSON.stringify({ detail: "invalid api key" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        }),
    );
    const client = new WakeApiClient({ fetchImpl: fetchSpy });
    await expect(client.listSessions()).rejects.toMatchObject({
      status: 401,
      isAuthError: true,
    });
  });
});
