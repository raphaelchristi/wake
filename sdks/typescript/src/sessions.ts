/**
 * Sessions resource: CRUD + interrupt + events + streaming.
 */

import type { WakeClient } from "./client.js";
import { iterSessionStream } from "./sse.js";
import type {
  Event,
  EventCreateRequest,
  EventList,
  EventType,
  Session,
  SessionCreateRequest,
  SessionList,
  SessionListQuery,
  StreamOptions,
} from "./types.js";

export class SessionsResource {
  constructor(private readonly client: WakeClient) {}

  async create(
    params: SessionCreateRequest,
    options: { idempotencyKey?: string; signal?: AbortSignal } = {}
  ): Promise<Session> {
    return this.client.request<Session>("POST", "/v1/sessions", {
      body: params,
      idempotencyKey: options.idempotencyKey,
      signal: options.signal,
    });
  }

  async list(query: SessionListQuery = {}, options: { signal?: AbortSignal } = {}): Promise<Session[]> {
    const res = await this.client.request<SessionList>("GET", "/v1/sessions", {
      query: query as Record<string, unknown>,
      signal: options.signal,
    });
    return res?.data ?? [];
  }

  async get(sessionId: string, options: { signal?: AbortSignal } = {}): Promise<Session> {
    return this.client.request<Session>(
      "GET",
      `/v1/sessions/${encodeURIComponent(sessionId)}`,
      { signal: options.signal }
    );
  }

  async delete(sessionId: string, options: { signal?: AbortSignal } = {}): Promise<void> {
    await this.client.request<void>(
      "DELETE",
      `/v1/sessions/${encodeURIComponent(sessionId)}`,
      { signal: options.signal }
    );
  }

  async interrupt(sessionId: string, options: { signal?: AbortSignal } = {}): Promise<Session> {
    return this.client.request<Session>(
      "POST",
      `/v1/sessions/${encodeURIComponent(sessionId)}/interrupt`,
      { signal: options.signal }
    );
  }

  async archive(sessionId: string, options: { signal?: AbortSignal } = {}): Promise<Session> {
    return this.client.request<Session>(
      "POST",
      `/v1/sessions/${encodeURIComponent(sessionId)}/archive`,
      { signal: options.signal }
    );
  }

  async appendEvent(
    sessionId: string,
    event: EventCreateRequest & { type: EventType },
    options: { idempotencyKey?: string; signal?: AbortSignal } = {}
  ): Promise<Event> {
    return this.client.request<Event>(
      "POST",
      `/v1/sessions/${encodeURIComponent(sessionId)}/events`,
      {
        body: event,
        idempotencyKey: options.idempotencyKey ?? event.idempotency_key,
        signal: options.signal,
      }
    );
  }

  async listEvents(
    sessionId: string,
    options: { since?: number; signal?: AbortSignal } = {}
  ): Promise<Event[]> {
    const res = await this.client.request<EventList>(
      "GET",
      `/v1/sessions/${encodeURIComponent(sessionId)}/events`,
      { query: { since: options.since ?? 0 }, signal: options.signal }
    );
    return res?.data ?? [];
  }

  /**
   * Stream events as they arrive. Returns an async iterator that
   * reconnects transparently on transport drops, forwarding the latest
   * `Last-Event-ID` so resumption is exact on the SSE layer.
   *
   * Usage:
   *
   * ```ts
   * for await (const ev of client.sessions.stream(session.id)) {
   *   if (ev.type === "assistant.delta") process.stdout.write(String(ev.payload.text ?? ""));
   * }
   * ```
   */
  stream(sessionId: string, options: StreamOptions = {}): AsyncIterableIterator<Event> {
    return iterSessionStream(this.client, sessionId, options);
  }
}
