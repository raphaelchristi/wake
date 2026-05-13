// Server-side relay for the OAuth callback. The browser POSTs
// `{ code, state }` here; we forward to the Wake backend's
// `GET /v1/vault/oauth/callback?code=&state=` and return the resulting
// credential metadata. Living server-side keeps the API key (when one
// is wired via WAKE_API_KEY env var) off the client URL and lets us
// translate backend errors into friendly JSON.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const BACKEND_BASE =
  process.env.NEXT_PUBLIC_WAKE_API_BASE ?? "http://localhost:8080";

export const runtime = "nodejs";

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

  const url = new URL("/v1/vault/oauth/callback", BACKEND_BASE);
  url.searchParams.set("code", body.code);
  url.searchParams.set("state", body.state);

  const headers: Record<string, string> = { Accept: "application/json" };
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
