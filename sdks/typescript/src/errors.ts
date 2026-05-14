/**
 * Error hierarchy. Every exception raised by the SDK derives from
 * `WakeClientError`, so consumers can catch the entire surface with a single
 * try/catch.
 */

export class WakeClientError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WakeClientError";
  }
}

export class WakeTransportError extends WakeClientError {
  override name = "WakeTransportError";
  override readonly cause?: unknown;
  constructor(message: string, cause?: unknown) {
    super(message);
    this.cause = cause;
  }
}

export class WakeAPIError extends WakeClientError {
  override name = "WakeAPIError";
  readonly status: number;
  readonly body: unknown;
  readonly detail: string | null;

  constructor(status: number, body: unknown, detail: string | null = null) {
    super(`HTTP ${status}: ${detail ?? (typeof body === "string" ? body : JSON.stringify(body))}`);
    this.status = status;
    this.body = body;
    this.detail = detail;
  }
}

export class WakeAuthError extends WakeAPIError {
  override name = "WakeAuthError";
}

export class WakeNotFoundError extends WakeAPIError {
  override name = "WakeNotFoundError";
}

export class WakeRateLimitError extends WakeAPIError {
  override name = "WakeRateLimitError";
  readonly retryAfter: number | null;

  constructor(status: number, body: unknown, detail: string | null = null, retryAfter: number | null = null) {
    super(status, body, detail);
    this.retryAfter = retryAfter;
  }
}

export class WakeServerError extends WakeAPIError {
  override name = "WakeServerError";
}

/**
 * Map an HTTP response to the appropriate error subclass.
 */
export function errorForResponse(status: number, body: unknown, retryAfter: number | null): WakeAPIError {
  let detail: string | null = null;
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    detail = typeof d === "string" ? d : JSON.stringify(d);
  }
  if (status === 401 || status === 403) return new WakeAuthError(status, body, detail);
  if (status === 404) return new WakeNotFoundError(status, body, detail);
  if (status === 429) return new WakeRateLimitError(status, body, detail, retryAfter);
  if (status >= 500 && status < 600) return new WakeServerError(status, body, detail);
  return new WakeAPIError(status, body, detail);
}
