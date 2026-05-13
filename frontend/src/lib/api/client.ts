// TODO: dashboard-shell slice owns the canonical client. This minimal
// implementation lets the metrics + vault slice typecheck before merge.
// When the shell lands, this file is overwritten by the shell version,
// which adds typed convenience methods generated from OpenAPI.

import { getApiKey } from "@/lib/auth";

const DEFAULT_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_WAKE_API_BASE) ||
  "http://localhost:8080";

export class WakeApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "WakeApiError";
    this.status = status;
    this.body = body;
  }

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

  private get apiKey(): string | null {
    return this.apiKeyOverride !== undefined ? this.apiKeyOverride : getApiKey();
  }

  async request<T>(
    path: string,
    init: RequestInit & { searchParams?: Record<string, string | number | undefined | null> } = {},
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (init.searchParams) {
      for (const [k, v] of Object.entries(init.searchParams)) {
        if (v !== undefined && v !== null && v !== "") {
          url.searchParams.set(k, String(v));
        }
      }
    }
    const headers = new Headers(init.headers);
    if (!headers.has("Content-Type") && init.body) {
      headers.set("Content-Type", "application/json");
    }
    const key = this.apiKey;
    if (key) headers.set("X-Wake-API-Key", key);

    const res = await this.fetchImpl(url, { ...init, headers });
    let body: unknown = null;
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/json")) {
      body = await res.json().catch(() => null);
    } else {
      body = await res.text().catch(() => "");
    }
    if (!res.ok) {
      throw new WakeApiError(
        `wake API ${res.status} on ${path}`,
        res.status,
        body,
      );
    }
    return body as T;
  }

  get<T>(path: string, searchParams?: Record<string, string | number | undefined | null>) {
    return this.request<T>(path, { method: "GET", searchParams });
  }

  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: "DELETE" });
  }
}

let _singleton: WakeApiClient | null = null;
export function getClient(): WakeApiClient {
  if (_singleton === null) _singleton = new WakeApiClient();
  return _singleton;
}
