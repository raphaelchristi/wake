/**
 * SSE streaming helper — `GET /v1/sessions/{id}/stream`.
 *
 * Implemented on top of `fetch()` with a manual SSE parser so the same code
 * path works in browsers, Node, Deno and Bun without the `EventSource`
 * limitations (no custom headers in the spec, no abort, no Node support).
 *
 * Behavior:
 *   - Filters server-side `heartbeat` frames.
 *   - Tracks `Last-Event-ID` between reconnects so resumption is exact on
 *     the SSE layer (server replays anything we missed).
 *   - Reconnects on transport drops (NetworkError, premature stream end) up
 *     to `maxReconnects` times with exponential backoff capped at 10s.
 *   - 4xx responses are surfaced via the regular `errorForResponse` mapping
 *     and never retried — `404` raises `WakeNotFoundError`, etc.
 */

import type { WakeClient } from "./client.js";
import { errorForResponse, WakeTransportError, type WakeAPIError } from "./errors.js";
import type { Event, StreamOptions } from "./types.js";

const DEFAULT_MAX_RECONNECTS = 5;
const RECONNECT_BACKOFF_MS = 500;
const RECONNECT_CAP_MS = 10_000;
const HEARTBEAT_EVENT = "heartbeat";
const DATA_EVENT = "event";

/** Internal: one parsed SSE frame. */
interface SSEFrame {
  event: string | null;
  data: string;
  id: string | null;
}

/**
 * Yield :class:`Event` objects from the session SSE stream.
 *
 * The returned object is an async iterator AND an async iterable — `for await`
 * works directly. Closing the iterator (via `break`, `return`, or `throw`)
 * cleanly aborts the underlying fetch.
 */
export function iterSessionStream(
  client: WakeClient,
  sessionId: string,
  options: StreamOptions = {}
): AsyncIterableIterator<Event> {
  const maxReconnects = options.maxReconnects ?? DEFAULT_MAX_RECONNECTS;
  let lastId: string | null = options.lastEventId ?? null;
  let cursor: number | null = options.since ?? null;

  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  let controller: AbortController | null = null;
  let attempts = 0;
  let finished = false;
  let buffer = "";

  const userSignal = options.signal;
  if (userSignal?.aborted) finished = true;
  const onUserAbort = () => {
    finished = true;
    controller?.abort(userSignal?.reason);
  };
  userSignal?.addEventListener("abort", onUserAbort, { once: true });

  async function openConnection(): Promise<void> {
    const url = new URL(
      `${client.baseUrl}/v1/sessions/${encodeURIComponent(sessionId)}/stream`
    );
    if (cursor !== null && lastId === null) {
      url.searchParams.set("since", String(cursor));
    }

    const extra: Record<string, string> = {};
    if (lastId) extra["Last-Event-ID"] = lastId;

    controller = new AbortController();
    if (userSignal) {
      if (userSignal.aborted) {
        controller.abort(userSignal.reason);
      } else {
        userSignal.addEventListener("abort", () => controller?.abort(userSignal.reason), { once: true });
      }
    }

    const response = await client.fetcher(url.toString(), {
      method: "GET",
      headers: client.streamHeaders(extra),
      signal: controller.signal,
    });

    if (!response.ok) {
      // Drain to release the connection then translate.
      let body: unknown = null;
      const text = await response.text().catch(() => "");
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = text;
        }
      }
      const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
      throw errorForResponse(response.status, body, retryAfter);
    }
    if (!response.body) {
      throw new WakeTransportError("SSE response missing body");
    }
    reader = response.body.getReader();
    buffer = "";
    attempts = 0;
  }

  async function reconnect(cause: unknown): Promise<void> {
    attempts += 1;
    if (attempts > maxReconnects) {
      throw new WakeTransportError(
        `SSE stream failed after ${maxReconnects} reconnects: ${describe(cause)}`,
        cause
      );
    }
    const delay = Math.min(RECONNECT_BACKOFF_MS * 2 ** (attempts - 1), RECONNECT_CAP_MS);
    await sleep(delay);
  }

  async function closeReader(): Promise<void> {
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        // ignore
      }
      reader = null;
    }
    controller?.abort();
    controller = null;
  }

  const iterator: AsyncIterableIterator<Event> = {
    [Symbol.asyncIterator]() {
      return iterator;
    },

    async next(): Promise<IteratorResult<Event>> {
      if (finished) {
        await closeReader();
        return { value: undefined as unknown as Event, done: true };
      }

      const decoder = new TextDecoder("utf-8");

      while (true) {
        if (finished) {
          await closeReader();
          return { value: undefined as unknown as Event, done: true };
        }

        if (!reader) {
          try {
            await openConnection();
          } catch (err) {
            if (isWakeAPIError(err)) throw err;
            try {
              await reconnect(err);
              continue;
            } catch (giveUp) {
              finished = true;
              throw giveUp;
            }
          }
        }

        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader!.read();
        } catch (err) {
          // Transport drop mid-stream — reconnect.
          reader = null;
          try {
            await reconnect(err);
            continue;
          } catch (giveUp) {
            finished = true;
            throw giveUp;
          }
        }

        if (chunk.done) {
          // Clean EOF: try to flush buffered frame, then stop.
          const tail = flushFrame(buffer);
          buffer = "";
          await closeReader();
          if (tail) {
            const ev = handleFrame(tail);
            if (ev) {
              lastId = tail.id ?? lastId;
              cursor = ev.seq + 1;
              return { value: ev, done: false };
            }
          }
          finished = true;
          return { value: undefined as unknown as Event, done: true };
        }

        buffer += decoder.decode(chunk.value, { stream: true });

        let nl: number;
        while ((nl = findFrameEnd(buffer)) !== -1) {
          const raw = buffer.slice(0, nl);
          buffer = buffer.slice(nl).replace(/^\r?\n\r?\n/, "");
          const frame = flushFrame(raw);
          if (!frame) continue;
          const ev = handleFrame(frame);
          if (ev) {
            lastId = frame.id ?? lastId;
            cursor = ev.seq + 1;
            return { value: ev, done: false };
          }
        }
        // Need more data — loop back to read again.
      }
    },

    async return(value?: Event): Promise<IteratorResult<Event>> {
      finished = true;
      await closeReader();
      userSignal?.removeEventListener("abort", onUserAbort);
      return { value: value as Event, done: true };
    },

    async throw(err?: unknown): Promise<IteratorResult<Event>> {
      finished = true;
      await closeReader();
      userSignal?.removeEventListener("abort", onUserAbort);
      throw err;
    },
  };

  return iterator;
}

// -- Frame parsing ----------------------------------------------------------

function findFrameEnd(buffer: string): number {
  // SSE frames are separated by a blank line (either "\n\n" or "\r\n\r\n").
  const idxLF = buffer.indexOf("\n\n");
  const idxCRLF = buffer.indexOf("\r\n\r\n");
  if (idxLF === -1) return idxCRLF;
  if (idxCRLF === -1) return idxLF;
  return Math.min(idxLF, idxCRLF);
}

function flushFrame(raw: string): SSEFrame | null {
  if (!raw.trim()) return null;
  let event: string | null = null;
  let id: string | null = null;
  const dataParts: string[] = [];

  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    let field: string;
    let value: string;
    if (colon === -1) {
      field = line;
      value = "";
    } else {
      field = line.slice(0, colon);
      value = line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
    }
    switch (field) {
      case "event":
        event = value;
        break;
      case "id":
        id = value;
        break;
      case "data":
        dataParts.push(value);
        break;
      // retry: ignored — we drive backoff ourselves.
      default:
        break;
    }
  }
  return { event, data: dataParts.join("\n"), id };
}

function handleFrame(frame: SSEFrame): Event | null {
  if (frame.event === HEARTBEAT_EVENT) return null;
  if (frame.event && frame.event !== DATA_EVENT) return null;
  if (!frame.data) return null;
  try {
    return JSON.parse(frame.data) as Event;
  } catch {
    // Malformed frame — drop it.
    return null;
  }
}

// -- helpers ---------------------------------------------------------------

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  if (Number.isFinite(n)) return Math.max(0, n * 1000);
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function describe(err: unknown): string {
  if (err instanceof Error) return err.message;
  try {
    return String(err);
  } catch {
    return "unknown error";
  }
}

function isWakeAPIError(err: unknown): err is WakeAPIError {
  return (
    typeof err === "object" &&
    err !== null &&
    (err as { name?: string }).name?.startsWith("Wake") === true &&
    "status" in (err as Record<string, unknown>) &&
    typeof (err as { status?: unknown }).status === "number"
  );
}
