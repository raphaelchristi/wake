/**
 * Core `WakeClient` — fetch-based, browser + Node compatible.
 *
 * Construct with a base URL + credentials + tenant scope. Access
 * `client.sessions` and `client.agents` for the resource bags.
 */

import { AgentsResource } from "./agents.js";
import { errorForResponse, WakeTransportError, type WakeAPIError } from "./errors.js";
import { SessionsResource } from "./sessions.js";

export const HEADER_API_KEY = "X-Wake-API-Key";
export const HEADER_ORG_ID = "X-Wake-Organization-Id";
export const HEADER_WS_ID = "X-Wake-Workspace-Id";
export const HEADER_USER_ID = "X-Wake-User-Id";
export const ENV_API_KEY = "WAKE_API_KEY";

const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_BACKOFF_BASE_MS = 250;
const DEFAULT_BACKOFF_CAP_MS = 8000;
const DEFAULT_TIMEOUT_MS = 30_000;

const MUTATING_METHODS = new Set(["POST", "PATCH", "PUT"]);
const VERSION = "0.1.0";

export interface WakeClientOptions {
  /** Wake API base URL, e.g. "https://wake.example.com". Trailing slash trimmed. */
  baseUrl: string;
  /**
   * API key for `X-Wake-API-Key`. Falls back to `process.env.WAKE_API_KEY`
   * when omitted (Node only); set `null` to disable the header.
   */
  apiKey?: string | null;
  /** Tenant scope. Default "default". */
  organizationId?: string;
  /** Workspace scope. Default "default". */
  workspaceId?: string;
  /** Optional `X-Wake-User-Id` — required when the server has RBAC on. */
  userId?: string;
  /** Per-request timeout in ms. Default 30s. */
  timeoutMs?: number;
  /** Max retries for retriable verbs/status codes. Default 3. */
  maxRetries?: number;
  /** Override the fetch implementation (useful for tests + Node 16 polyfills). */
  fetch?: typeof fetch;
}

export interface RequestOptions {
  query?: Record<string, unknown>;
  body?: unknown;
  /** Override the global retry count for this call (e.g. for idempotent POSTs). */
  retries?: number;
  /** Send an `Idempotency-Key` header (24h dedupe window on the server). */
  idempotencyKey?: string;
  /** Abort signal threaded through `fetch`. */
  signal?: AbortSignal;
}

export class WakeClient {
  readonly baseUrl: string;
  readonly organizationId: string;
  readonly workspaceId: string;
  readonly userId: string | undefined;
  readonly timeoutMs: number;
  readonly maxRetries: number;

  private readonly apiKey: string | null;
  private readonly fetchImpl: typeof fetch;

  readonly sessions: SessionsResource;
  readonly agents: AgentsResource;

  constructor(options: WakeClientOptions) {
    if (!options.baseUrl) {
      throw new Error("baseUrl is required");
    }
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.apiKey =
      options.apiKey === undefined ? resolveEnvApiKey() : options.apiKey ?? null;
    this.organizationId = options.organizationId ?? "default";
    this.workspaceId = options.workspaceId ?? "default";
    this.userId = options.userId;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = Math.max(0, options.maxRetries ?? DEFAULT_MAX_RETRIES);

    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (!fetchImpl) {
      throw new Error(
        "Global `fetch` is not available — pass `options.fetch` or upgrade to Node 18+."
      );
    }
    this.fetchImpl = fetchImpl;

    this.sessions = new SessionsResource(this);
    this.agents = new AgentsResource(this);
  }

  /**
   * Build the default header set. Exposed so the SSE module can reuse it.
   */
  defaultHeaders(): Record<string, string> {
    const h: Record<string, string> = {
      [HEADER_ORG_ID]: this.organizationId,
      [HEADER_WS_ID]: this.workspaceId,
      "User-Agent": `wake-ai-client-ts/${VERSION}`,
    };
    if (this.apiKey) h[HEADER_API_KEY] = this.apiKey;
    if (this.userId) h[HEADER_USER_ID] = this.userId;
    return h;
  }

  /**
   * Headers used for SSE streams — same as default but `Accept: text/event-stream`.
   */
  streamHeaders(extra?: Record<string, string>): Record<string, string> {
    return { ...this.defaultHeaders(), Accept: "text/event-stream", ...(extra ?? {}) };
  }

  /**
   * The bound `fetch` implementation. SSE module uses this.
   */
  get fetcher(): typeof fetch {
    return this.fetchImpl;
  }

  /**
   * Send a JSON request and return the parsed body. Retries 429/5xx
   * (honoring `Retry-After`) for idempotent verbs by default.
   */
  async request<T = unknown>(
    method: string,
    path: string,
    options: RequestOptions = {}
  ): Promise<T> {
    let maxRetries = options.retries ?? this.maxRetries;
    if (options.retries === undefined && MUTATING_METHODS.has(method.toUpperCase())) {
      maxRetries = 0;
    }

    const url = this.buildUrl(path, options.query);
    const headers: Record<string, string> = {
      ...this.defaultHeaders(),
      Accept: "application/json",
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

    let attempt = 0;
    while (true) {
      const init: RequestInit = {
        method,
        headers,
        signal: this.compositeSignal(options.signal),
      };
      if (options.body !== undefined) init.body = JSON.stringify(options.body);

      let response: Response;
      try {
        response = await this.fetchImpl(url, init);
      } catch (err) {
        if (attempt >= maxRetries) {
          throw new WakeTransportError(
            err instanceof Error ? err.message : String(err),
            err
          );
        }
        await sleep(backoffMs(attempt));
        attempt += 1;
        continue;
      }

      if (response.ok) {
        if (response.status === 204) return undefined as T;
        const text = await response.text();
        if (!text) return undefined as T;
        try {
          return JSON.parse(text) as T;
        } catch {
          return text as unknown as T;
        }
      }

      // Error path — retry on 429 / 5xx
      const retriable = response.status === 429 || (response.status >= 500 && response.status < 600);
      if (retriable && attempt < maxRetries) {
        const hint = parseRetryAfter(response.headers.get("Retry-After"));
        await sleep(hint ?? backoffMs(attempt));
        attempt += 1;
        continue;
      }
      throw await this.errorForResponse(response);
    }
  }

  // -- Internals ------------------------------------------------------------

  private buildUrl(path: string, query?: Record<string, unknown>): string {
    const u = new URL(`${this.baseUrl}${path}`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v === undefined || v === null || v === "") continue;
        u.searchParams.set(k, v instanceof Date ? v.toISOString() : String(v));
      }
    }
    return u.toString();
  }

  private compositeSignal(external: AbortSignal | undefined): AbortSignal {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("timeout")), this.timeoutMs);
    const cleanup = () => clearTimeout(timer);

    if (external) {
      if (external.aborted) controller.abort(external.reason);
      external.addEventListener("abort", () => controller.abort(external.reason), { once: true });
    }
    controller.signal.addEventListener("abort", cleanup, { once: true });
    return controller.signal;
  }

  private async errorForResponse(response: Response): Promise<WakeAPIError> {
    let body: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
    return errorForResponse(response.status, body, retryAfter);
  }
}

function parseRetryAfter(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  if (Number.isFinite(n)) return Math.max(0, n * 1000);
  return null;
}

function backoffMs(attempt: number): number {
  return Math.min(DEFAULT_BACKOFF_BASE_MS * 2 ** attempt, DEFAULT_BACKOFF_CAP_MS);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolveEnvApiKey(): string | null {
  // Node-only — guarded so the browser bundle stays free of `process`.
  if (typeof process !== "undefined" && process?.env) {
    const v = process.env[ENV_API_KEY];
    return v ? v : null;
  }
  return null;
}
