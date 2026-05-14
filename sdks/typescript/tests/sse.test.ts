import { describe, expect, it } from "vitest";
import { WakeClient, WakeNotFoundError, WakeTransportError } from "../src/index.js";
import {
  brokenSSEResponse,
  eventPayload,
  makeMockFetch,
  sseFrame,
  streamingSSEResponse,
} from "./helpers.js";

describe("session streaming", () => {
  it("yields events parsed from SSE frames", async () => {
    const { fetch } = makeMockFetch(async () =>
      streamingSSEResponse([
        sseFrame("event", eventPayload(0), "evt_00"),
        sseFrame("event", eventPayload(1, { type: "assistant.delta" }), "evt_01"),
      ])
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const collected: number[] = [];
    for await (const ev of c.sessions.stream("sess_01")) {
      collected.push(ev.seq);
    }
    expect(collected).toEqual([0, 1]);
  });

  it("filters heartbeat frames", async () => {
    const { fetch } = makeMockFetch(async () =>
      streamingSSEResponse([
        sseFrame("heartbeat", { ts: "2026-01-01T00:00:00Z" }),
        sseFrame("event", eventPayload(0), "evt_00"),
        sseFrame("heartbeat", { ts: "2026-01-01T00:00:01Z" }),
        sseFrame("event", eventPayload(1), "evt_01"),
      ])
    );
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const events = [];
    for await (const ev of c.sessions.stream("sess_01")) events.push(ev);
    expect(events.length).toBe(2);
  });

  it("reconnects after a transport drop and resumes via Last-Event-ID", async () => {
    let calls = 0;
    const headersSeen: Array<string | undefined> = [];
    const { fetch } = makeMockFetch(async (req) => {
      calls += 1;
      headersSeen.push(req.headers["last-event-id"]);
      if (calls === 1) {
        // First connection yields one event, then drops mid-stream.
        return brokenSSEResponse([sseFrame("event", eventPayload(0), "evt_00")]);
      }
      // Second connection delivers the rest cleanly.
      return streamingSSEResponse([sseFrame("event", eventPayload(1), "evt_01")]);
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const seqs: number[] = [];
    for await (const ev of c.sessions.stream("sess_01")) {
      seqs.push(ev.seq);
      if (seqs.length >= 2) break;
    }
    expect(seqs).toEqual([0, 1]);
    expect(calls).toBe(2);
    expect(headersSeen[0]).toBeUndefined();
    expect(headersSeen[1]).toBe("evt_00");
  });

  it("4xx surface as WakeAPIError subclass and do not retry", async () => {
    let calls = 0;
    const { fetch } = makeMockFetch(async () => {
      calls += 1;
      return new Response(JSON.stringify({ detail: "session not found" }), { status: 404 });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    await expect(async () => {
      // eslint-disable-next-line no-unused-vars
      for await (const _ of c.sessions.stream("missing")) {
        // unreachable
      }
    }).rejects.toBeInstanceOf(WakeNotFoundError);
    expect(calls).toBe(1);
  });

  it("forwards `since` as a query param when no lastEventId", async () => {
    const { fetch, recorded } = makeMockFetch(async () => streamingSSEResponse([]));
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    // eslint-disable-next-line no-unused-vars
    for await (const _ of c.sessions.stream("sess_01", { since: 5 })) {
      // empty stream
    }
    const url = new URL(recorded[0]!.url);
    expect(url.searchParams.get("since")).toBe("5");
    expect(recorded[0]!.headers["accept"]).toBe("text/event-stream");
  });

  it("gives up after maxReconnects transport failures", async () => {
    const { fetch } = makeMockFetch(async () => {
      throw new TypeError("net down");
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    await expect(async () => {
      // eslint-disable-next-line no-unused-vars
      for await (const _ of c.sessions.stream("sess_01", { maxReconnects: 1 })) {
        // unreachable
      }
    }).rejects.toBeInstanceOf(WakeTransportError);
  }, 20_000);

  it("closing the iterator cancels the request", async () => {
    let aborted = false;
    const { fetch } = makeMockFetch(async () => {
      // Build a response whose stream waits forever until aborted from outside.
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(sseFrame("event", eventPayload(0), "evt_00")));
        },
        cancel() {
          aborted = true;
        },
      });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });
    const c = new WakeClient({ baseUrl: "http://wake.test", fetch });
    const iter = c.sessions.stream("sess_01");
    const first = await iter.next();
    expect(first.done).toBe(false);
    await iter.return!();
    // Give the cancel callback a turn of the event loop.
    await new Promise((r) => setTimeout(r, 0));
    expect(aborted).toBe(true);
  });
});
