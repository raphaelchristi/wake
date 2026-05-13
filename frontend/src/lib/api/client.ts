/**
 * Minimal API client stub.
 *
 * STUB — owned by dashboard-shell. This file ships a tiny implementation so
 * the replay slice can compile + test in isolation. When dashboard-shell
 * merges, this file is expected to be REPLACED by the shell's full client
 * (which adds auth, retries, generated OpenAPI types, etc.). The shape
 * contract preserved here is the `request<T>()` helper and `API_BASE` env
 * resolution.
 *
 * TODO(dashboard-shell merge): delete this stub and import from the shell.
 */

const DEFAULT_BASE = "http://localhost:8080";

export function getApiBase(): string {
  if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_WAKE_API_URL) {
    return process.env.NEXT_PUBLIC_WAKE_API_URL;
  }
  if (typeof window !== "undefined") {
    return (window as { __WAKE_API_URL__?: string }).__WAKE_API_URL__ ?? DEFAULT_BASE;
  }
  return DEFAULT_BASE;
}

function readAuthHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const key = window.localStorage?.getItem("wake.apiKey");
  return key ? { "X-Wake-API-Key": key } : {};
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const base = getApiBase();
  const url = path.startsWith("http") ? path : `${base}${path}`;
  const headers = {
    "Content-Type": "application/json",
    ...readAuthHeader(),
    ...(init.headers ?? {}),
  };
  const resp = await fetch(url, { ...init, headers });
  if (!resp.ok) {
    let body: unknown = null;
    try {
      body = await resp.json();
    } catch {
      // ignore
    }
    throw new ApiError(
      resp.status,
      `Wake API ${resp.status} ${resp.statusText}`,
      body,
    );
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
