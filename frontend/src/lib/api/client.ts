/**
 * Thin fetch wrapper for the Wake API.
 *
 * Responsibilities:
 *   - Inject the `X-Wake-API-Key` header from local auth state.
 *   - Surface non-2xx responses as `WakeApiError` with a parsed body.
 *   - Provide typed convenience methods for the routes the dashboard needs.
 *
 * Networking knobs (timeouts, retries) live in TanStack Query — this layer
 * only does the one HTTP round-trip.
 */
import { getApiKey } from "@/lib/auth";

import type {
  AgentList,
  EventList,
  HealthResponse,
  Session,
  SessionList,
  SessionListQuery,
} from "./types";

/**
 * Resolve the browser-side API base URL.
 *
 * Canonical (Phase 5.1): `NEXT_PUBLIC_WAKE_API_BASE`.
 *
 * Legacy `NEXT_PUBLIC_API_URL` is accepted for one transition release
 * with a runtime `console.warn`. It will be removed in v0.6. Any
 * deploy that still relies on it must rename the env var.
 */
function resolveDefaultBase(): string {
  if (typeof process === "undefined") return "http://localhost:8080";
  const canon = process.env.NEXT_PUBLIC_WAKE_API_BASE;
  if (canon) return canon;
  const legacy = process.env.NEXT_PUBLIC_API_URL;
  if (legacy) {
    // Hint operators upgrading from the pre-5.1 chart. We only warn
    // once per process — Next.js may re-evaluate this module across
    // RSC boundaries so we stash a flag on globalThis.
    const g = globalThis as { __wakeApiBaseDeprecationWarned?: boolean };
    if (!g.__wakeApiBaseDeprecationWarned) {
      g.__wakeApiBaseDeprecationWarned = true;
      // eslint-disable-next-line no-console
      console.warn(
        "[wake] DEPRECATED: NEXT_PUBLIC_API_URL is no longer supported; " +
          "use NEXT_PUBLIC_WAKE_API_BASE. Legacy fallback will be removed in v0.6.",
      );
    }
    return legacy;
  }
  return "http://localhost:8080";
}

const DEFAULT_BASE = resolveDefaultBase();

export class WakeApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "WakeApiError";
    this.status = status;
    this.body = body;
  }

  /** True for HTTP 401/403 — caller should bounce to /login. */
  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

export interface ClientOptions {
  baseUrl?: string;
  apiKey?: string | null;
  fetchImpl?: typeof fetch;
}

export class WakeApiClient {
  private readonly baseUrl: string;
  private readonly apiKeyOverride: string | null | undefined;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE).replace(/\/$/, "");
    this.apiKeyOverride = options.apiKey;
    this.fetchImpl = options.fetchImpl ?? fetch.bind(globalThis);
  }

  private apiKey(): string | null {
    if (this.apiKeyOverride !== undefined) return this.apiKeyOverride;
    return getApiKey();
  }

  private headers(extra?: HeadersInit): Headers {
    const h = new Headers(extra);
    const key = this.apiKey();
    if (key) h.set("X-Wake-API-Key", key);
    if (!h.has("Accept")) h.set("Accept", "application/json");
    return h;
  }

  /**
   * Public escape hatch for hooks that need raw HTTP control
   * (used by replay + metrics-vault hooks). Same semantics as the
   * typed convenience methods below.
   */
  async raw<T>(
    method: string,
    path: string,
    options: { query?: Record<string, unknown>; body?: unknown } = {},
  ): Promise<T> {
    return this.request<T>(method, path, options);
  }

  private async request<T>(
    method: string,
    path: string,
    options: { query?: Record<string, unknown>; body?: unknown } = {},
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (options.query) {
      for (const [k, v] of Object.entries(options.query)) {
        if (v === undefined || v === null || v === "") continue;
        url.searchParams.set(k, String(v));
      }
    }

    const init: RequestInit = {
      method,
      headers: this.headers(options.body ? { "Content-Type": "application/json" } : undefined),
    };
    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }

    const res = await this.fetchImpl(url.toString(), init);
    const text = await res.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!res.ok) {
      const detail =
        parsed && typeof parsed === "object" && "detail" in parsed
          ? String((parsed as { detail?: unknown }).detail)
          : res.statusText;
      throw new WakeApiError(`${method} ${path} → ${res.status} ${detail}`, res.status, parsed);
    }
    return parsed as T;
  }

  // -- routes used by the shell slice ----------------------------------------

  health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/health");
  }

  listSessions(query: SessionListQuery = {}): Promise<SessionList> {
    return this.request<SessionList>("GET", "/v1/sessions", {
      query: query as Record<string, unknown>,
    });
  }

  getSession(id: string): Promise<Session> {
    return this.request<Session>("GET", `/v1/sessions/${encodeURIComponent(id)}`);
  }

  listAgents(): Promise<AgentList> {
    return this.request<AgentList>("GET", "/v1/agents");
  }

  listEvents(sessionId: string, since = 0): Promise<EventList> {
    return this.request<EventList>(
      "GET",
      `/v1/sessions/${encodeURIComponent(sessionId)}/events`,
      { query: { since } },
    );
  }

  // -- generic verb helpers (used by replay + metrics-vault hooks) -----------

  get<T>(path: string, query?: Record<string, unknown>): Promise<T> {
    return this.request<T>("GET", path, { query });
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, { body });
  }

  delete<T = void>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }
}

/** Lazily-instantiated default client. */
let defaultClient: WakeApiClient | null = null;
export function getDefaultClient(): WakeApiClient {
  if (!defaultClient) defaultClient = new WakeApiClient();
  return defaultClient;
}

/** Alias kept for compatibility with hooks introduced by replay + metrics-vault slices. */
export const getClient = getDefaultClient;

/**
 * Standalone request helper used by hooks that don't need a `WakeApiClient` instance.
 * Wraps the default client with a method+path+query+body shape.
 */
/**
 * Standalone fetch helper used by replay hooks. Signature:
 *   request(path)             → GET path
 *   request(path, options)    → GET path with query/body
 *   request(method, path, ?)  → arbitrary method
 *
 * Returns the parsed JSON body, typed as `T`.
 */
export async function request<T>(
  pathOrMethod: string,
  pathOrOptions?: string | { query?: Record<string, unknown>; body?: unknown },
  options: { query?: Record<string, unknown>; body?: unknown } = {},
): Promise<T> {
  const client = getDefaultClient();
  // request("GET", "/path", { query: {...} })
  if (typeof pathOrOptions === "string") {
    return client.raw<T>(pathOrMethod, pathOrOptions, options);
  }
  // request("/path") or request("/path", { query }) → defaults to GET
  return client.raw<T>("GET", pathOrMethod, pathOrOptions ?? {});
}

/** Test-only — reset the default client between cases. */
export function _resetDefaultClient(): void {
  defaultClient = null;
}
