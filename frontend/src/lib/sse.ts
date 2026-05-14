/**
 * EventSource utilities. The shell slice provides a thin reconnecting wrapper
 * that the replay/metrics slices can build on top of. SSE is the canonical
 * real-time channel for Wake (see the `GET /v1/sessions/{id}/stream` route).
 *
 * Tenancy:
 *   - O backend Wake exige `X-Wake-Organization-Id` / `X-Wake-Workspace-Id`
 *     em todas as requests. `EventSource` no browser não permite custom
 *     headers, então abrimos a connection via proxy Next.js
 *     (`/api/wake/sessions/{id}/stream?org=&ws=`) que injeta os headers.
 *   - `sseUrlForSession()` é a maneira canônica de construir essa URL
 *     com a query string sanitizada.
 */
import { getTenantScope } from "@/lib/tenant";

export type SSEEvent<T = unknown> = {
  /** Server-set event id, used for resume via Last-Event-ID. */
  id?: string;
  /** Event name (FastAPI sets this via the `event:` field, default `message`). */
  event: string;
  /** Parsed JSON data payload, or null if data was not JSON. */
  data: T;
};

export interface SSEOptions {
  /** Auth headers to attach (e.g. X-Wake-API-Key). */
  headers?: Record<string, string>;
  /** Initial Last-Event-ID. */
  lastEventId?: string;
  /** Called on each parsed event. */
  onEvent?: <T>(event: SSEEvent<T>) => void;
  /** Called on transport error before reconnect. */
  onError?: (error: Event) => void;
  /** Called when the underlying EventSource opens. */
  onOpen?: () => void;
}

/**
 * Constrói a URL do proxy SSE Next.js para uma sessão. Opcionalmente
 * aceita override do scope tenant (útil em testes); por padrão lê de
 * `getTenantScope()`.
 *
 * Importante: a query string `org`/`ws` é só transporte client→proxy.
 * O proxy re-injeta como headers ao falar com o backend, que é onde
 * a tenancy é realmente enforced.
 */
export function sseUrlForSession(
  sessionId: string,
  scope?: { organizationId: string; workspaceId: string },
): string {
  const tenant = scope ?? getTenantScope();
  const params = new URLSearchParams({
    org: tenant.organizationId,
    ws: tenant.workspaceId,
  });
  return `/api/wake/sessions/${encodeURIComponent(sessionId)}/stream?${params.toString()}`;
}

/**
 * Open an EventSource against the given URL. Returns a close handle.
 *
 * EventSource doesn't support custom headers in browsers; this helper accepts
 * `headers` so a future server-side proxy or polyfill can use them. For the
 * shell slice we rely on cookies or query params for auth on the SSE route —
 * but the API client uses headers, so consumers should encode the key as a
 * query string when needed. Wake API supports both today.
 */
export function openSSE(url: string, options: SSEOptions = {}): () => void {
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    // SSR / unsupported environment — no-op cleanly.
    return () => undefined;
  }

  const source = new EventSource(url, { withCredentials: false });

  source.addEventListener("open", () => options.onOpen?.());
  source.addEventListener("error", (err) => options.onError?.(err));
  source.addEventListener("message", (msg: MessageEvent) => {
    options.onEvent?.(parseEvent(msg, "message"));
  });

  return () => source.close();
}

function parseEvent<T>(msg: MessageEvent, defaultName: string): SSEEvent<T> {
  let data: unknown = msg.data;
  if (typeof msg.data === "string") {
    try {
      data = JSON.parse(msg.data);
    } catch {
      data = msg.data;
    }
  }
  return {
    id: msg.lastEventId || undefined,
    event: msg.type || defaultName,
    data: data as T,
  };
}
