// Server-side relay for the OAuth callback. The browser POSTs
// `{ code, state }` here; we forward to the Wake backend's
// `GET /v1/vault/oauth/callback?code=&state=` and return the resulting
// credential metadata. Living server-side keeps the API key (when one
// is wired via WAKE_API_KEY env var) off the client URL and lets us
// translate backend errors into friendly JSON.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Resolve the backend URL for the server-side OAuth callback proxy.
 *
 * Order of precedence (Phase 5.1 canon):
 *   1. `WAKE_API_URL`              — server-side, in-cluster Service URL
 *   2. `NEXT_PUBLIC_WAKE_API_BASE` — browser-facing public base, used as
 *                                    a fallback for single-host dev
 *   3. throw                       — production deploys MUST set at least
 *                                    one; no silent localhost fallback so
 *                                    the misconfiguration surfaces loudly.
 *
 * The `localhost:8080` default is preserved ONLY when running in
 * development (NODE_ENV !== "production"); otherwise we fail the
 * request with a clear error.
 */
function resolveBackendBase(): string {
  const serverSide = process.env.WAKE_API_URL?.trim();
  if (serverSide) return serverSide;
  const browserBase = process.env.NEXT_PUBLIC_WAKE_API_BASE?.trim();
  if (browserBase) return browserBase;
  if (process.env.NODE_ENV !== "production") {
    return "http://localhost:8080";
  }
  throw new Error(
    "OAuth callback proxy misconfigured: set WAKE_API_URL (preferred, " +
      "server-side, in-cluster) or NEXT_PUBLIC_WAKE_API_BASE.",
  );
}

export const runtime = "nodejs";

/**
 * Regex defensiva para tenant ids — bate com o backend
 * (`src/wake/tenancy.py`). Rejeita strings vazias, espaços, CRLF.
 */
const TENANT_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;
const DEFAULT_TENANT = "default";

function resolveTenantFromRequest(req: NextRequest): {
  organizationId: string;
  workspaceId: string;
  error?: string;
} {
  // Permite client passar via header (preferido — espelha o que o API
  // client browser-side já faz) ou via query string (fallback).
  const orgHeader = req.headers.get("x-wake-organization-id");
  const wsHeader = req.headers.get("x-wake-workspace-id");
  const url = new URL(req.url);
  const orgQuery = url.searchParams.get("org");
  const wsQuery = url.searchParams.get("ws");

  const org = (orgHeader ?? orgQuery ?? DEFAULT_TENANT).trim();
  const ws = (wsHeader ?? wsQuery ?? DEFAULT_TENANT).trim();

  if (!TENANT_RE.test(org)) {
    return { organizationId: DEFAULT_TENANT, workspaceId: DEFAULT_TENANT, error: "invalid org" };
  }
  if (!TENANT_RE.test(ws)) {
    return { organizationId: DEFAULT_TENANT, workspaceId: DEFAULT_TENANT, error: "invalid ws" };
  }
  return { organizationId: org, workspaceId: ws };
}

export async function POST(req: NextRequest) {
  let body: { code?: string; state?: string };
  try {
    body = (await req.json()) as { code?: string; state?: string };
  } catch {
    return NextResponse.json(
      { error: "invalid json body" },
      { status: 400 },
    );
  }
  if (!body.code || !body.state) {
    return NextResponse.json(
      { error: "missing 'code' or 'state' in body" },
      { status: 400 },
    );
  }

  const tenant = resolveTenantFromRequest(req);
  if (tenant.error) {
    return NextResponse.json({ error: tenant.error }, { status: 400 });
  }

  let url: URL;
  try {
    url = new URL("/v1/vault/oauth/callback", resolveBackendBase());
  } catch (err) {
    return NextResponse.json(
      {
        error:
          err instanceof Error ? err.message : "backend base url unresolved",
      },
      { status: 500 },
    );
  }
  url.searchParams.set("code", body.code);
  url.searchParams.set("state", body.state);

  const headers: Record<string, string> = {
    Accept: "application/json",
    // Encaminha tenancy para que a credencial seja gravada no workspace
    // correto pelo vault (sem isso o backend cairia em `default/default`).
    "X-Wake-Organization-Id": tenant.organizationId,
    "X-Wake-Workspace-Id": tenant.workspaceId,
  };
  // Allow opt-in server-side auth: operators can set WAKE_API_KEY on the
  // Next.js process so the callback proxy authenticates without leaking
  // the key into the browser.
  const apiKey = process.env.WAKE_API_KEY;
  if (apiKey) headers["X-Wake-API-Key"] = apiKey;

  // Forward the incoming cookie / auth header if the shell slice ends up
  // putting the API key into a cookie. Today auth.ts stores it in
  // localStorage so this is a no-op; harmless on the empty path.
  const incomingAuth = req.headers.get("x-wake-api-key");
  if (incomingAuth) headers["X-Wake-API-Key"] = incomingAuth;

  // Forward optional user id (slice A — RBAC). No-op quando ausente.
  const userId = req.headers.get("x-wake-user-id");
  if (userId) headers["X-Wake-User-Id"] = userId;

  const started = Date.now();
  // Never log raw `code` or `state` — they are short-lived credentials.
  // Log a digest of `state` instead so multiple log lines for the same
  // flow can be correlated without exposing the secret.
  const stateDigest = body.state.slice(0, 6) + "…";

  try {
    const upstream = await fetch(url, { method: "GET", headers, cache: "no-store" });
    const text = await upstream.text();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
    if (!upstream.ok) {
      const message =
        parsed && typeof parsed === "object" && "detail" in parsed
          ? String((parsed as { detail: unknown }).detail)
          : typeof parsed === "string"
            ? parsed
            : `backend ${upstream.status}`;
      console.warn(
        "[oauth-callback] upstream %d state=%s duration_ms=%d msg=%s",
        upstream.status,
        stateDigest,
        Date.now() - started,
        message,
      );
      return NextResponse.json(
        { error: message, status: upstream.status },
        { status: upstream.status },
      );
    }
    console.info(
      "[oauth-callback] success state=%s duration_ms=%d",
      stateDigest,
      Date.now() - started,
    );
    return NextResponse.json(parsed, { status: 200 });
  } catch (err) {
    console.error(
      "[oauth-callback] upstream error state=%s duration_ms=%d err=%s",
      stateDigest,
      Date.now() - started,
      err instanceof Error ? err.message : String(err),
    );
    return NextResponse.json(
      {
        error:
          err instanceof Error ? err.message : "unknown upstream failure",
      },
      { status: 502 },
    );
  }
}
