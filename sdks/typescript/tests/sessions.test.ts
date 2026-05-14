import { describe, expect, it } from "vitest";
import { WakeClient } from "../src/index.js";
import { agentPayload, eventPayload, makeMockFetch, sessionPayload } from "./helpers.js";

describe("sessions resource", () => {
  it("POST /v1/sessions includes the JSON body", async () => {
    const { fetch, recorded } = makeMockFetch(async () =>
      new Response(JSON.stringify(sessionPayload({ metadata: { trace: "abc" } })), { status: 201 })
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const s = await c.sessions.create({
      agent_id: "agent_01",
      metadata: { trace: "abc" },
    });
    expect(s.agent_id).toBe("agent_01");
    expect(s.metadata).toEqual({ trace: "abc" });
    expect(recorded[0]!.method).toBe("POST");
    expect(new URL(recorded[0]!.url).pathname).toBe("/v1/sessions");
  });

  it("GET /v1/sessions forwards filter query params", async () => {
    const { fetch, recorded } = makeMockFetch(async () =>
      new Response(JSON.stringify({ data: [sessionPayload()] }), { status: 200 })
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    await c.sessions.list({
      agent: "agent_01",
      status: "running",
      since: new Date("2026-01-01T00:00:00.000Z"),
      page: 2,
      page_size: 25,
    });
    const params = new URL(recorded[0]!.url).searchParams;
    expect(params.get("agent")).toBe("agent_01");
    expect(params.get("status")).toBe("running");
    expect(params.get("page")).toBe("2");
    expect(params.get("page_size")).toBe("25");
    expect(params.get("since")?.startsWith("2026-01-01")).toBe(true);
  });

  it("GET /v1/sessions/{id} fetches a single session", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      expect(new URL(req.url).pathname).toBe("/v1/sessions/sess_01");
      return new Response(JSON.stringify(sessionPayload()), { status: 200 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const s = await c.sessions.get("sess_01");
    expect(s.status).toBe("idle");
  });

  it("DELETE /v1/sessions/{id} returns void", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      expect(req.method).toBe("DELETE");
      return new Response(null, { status: 204 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    await expect(c.sessions.delete("sess_01")).resolves.toBeUndefined();
  });

  it("POST /v1/sessions/{id}/interrupt returns terminated session", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      expect(new URL(req.url).pathname).toBe("/v1/sessions/sess_01/interrupt");
      return new Response(JSON.stringify(sessionPayload({ status: "terminated" })), { status: 200 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const s = await c.sessions.interrupt("sess_01");
    expect(s.status).toBe("terminated");
  });

  it("appendEvent POSTs to /events path", async () => {
    const { fetch, recorded } = makeMockFetch(async (req) => {
      expect(new URL(req.url).pathname).toBe("/v1/sessions/sess_01/events");
      return new Response(JSON.stringify(eventPayload(1, { type: "user.message" })), { status: 202 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const ev = await c.sessions.appendEvent("sess_01", {
      type: "user.message",
      payload: { text: "hello" },
    });
    expect(ev.type).toBe("user.message");
    expect(ev.seq).toBe(1);
    expect(JSON.parse(recorded[0]!.body!)).toMatchObject({ type: "user.message" });
  });

  it("listEvents passes since=", async () => {
    const { fetch, recorded } = makeMockFetch(async () =>
      new Response(JSON.stringify({ data: [eventPayload(0), eventPayload(1)] }), { status: 200 })
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const events = await c.sessions.listEvents("sess_01", { since: 0 });
    expect(events.map((e) => e.seq)).toEqual([0, 1]);
    expect(new URL(recorded[0]!.url).searchParams.get("since")).toBe("0");
  });
});

describe("agents resource", () => {
  it("create + list", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      if (req.method === "POST") {
        return new Response(JSON.stringify(agentPayload()), { status: 201 });
      }
      return new Response(JSON.stringify({ data: [agentPayload()] }), { status: 200 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const created = await c.agents.create({
      name: "researcher",
      model: { id: "claude-opus-4-7" },
      system: "You are helpful.",
    });
    expect(created.id).toBe("agent_01");
    const list = await c.agents.list();
    expect(list.length).toBe(1);
  });

  it("get accepts version query param", async () => {
    const { fetch, recorded } = makeMockFetch(async () =>
      new Response(JSON.stringify(agentPayload({ version: 3 })), { status: 200 })
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const a = await c.agents.get("agent_01", { version: 3 });
    expect(a.version).toBe(3);
    expect(new URL(recorded[0]!.url).searchParams.get("version")).toBe("3");
  });

  it("update bumps version", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      expect(req.method).toBe("PATCH");
      return new Response(JSON.stringify(agentPayload({ version: 2, name: "renamed" })), { status: 200 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const a = await c.agents.update("agent_01", { name: "renamed" });
    expect(a.version).toBe(2);
    expect(a.name).toBe("renamed");
  });

  it("listVersions returns array", async () => {
    const { fetch } = makeMockFetch(async () =>
      new Response(JSON.stringify({ data: [1, 2, 3].map((v) => agentPayload({ version: v })) }), { status: 200 })
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const versions = await c.agents.listVersions("agent_01");
    expect(versions.map((a) => a.version)).toEqual([1, 2, 3]);
  });

  it("archive POSTs to /archive", async () => {
    const { fetch } = makeMockFetch(async (req) => {
      expect(new URL(req.url).pathname).toBe("/v1/agents/agent_01/archive");
      return new Response(JSON.stringify(agentPayload()), { status: 200 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const a = await c.agents.archive("agent_01");
    expect(a.id).toBe("agent_01");
  });
});
