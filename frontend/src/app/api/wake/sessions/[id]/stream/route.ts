/**
 * SSE proxy: `GET /api/wake/sessions/{id}/stream`.
 *
 * Por que existe:
 *   - Backend Wake (>= 89bec12) usa headers `X-Wake-Organization-Id` e
 *     `X-Wake-Workspace-Id` para escopar tenant. `EventSource` (browser API
 *     padrão) não permite custom headers. Esta rota Next.js faz proxy:
 *     traduz query string `org=&ws=` em headers e pipe da resposta.
 *   - Também injeta `X-Wake-API-Key` quando configurado no servidor
 *     (`WAKE_API_KEY`) para evitar leak no client.
 *
 * Modelo de segurança:
 *   - Esta rota NÃO é a fronteira real de tenancy — backend re-valida.
 *   - Sanitização defensiva via regex `^[a-z0-9][a-z0-9_-]{0,62}$`
 *     impede que valores patológicos (CRLF, nulls, paths) cheguem ao
 *     backend Wake como header. 400 para input inválido.
 *   - Limita o `id` da sessão à mesma regex para que `URL` join não
 *     mude o path base.
 *
 * Streaming:
 *   - Reusa o `ReadableStream` da resposta upstream — runtime Node.js
 *     do Next.js converte para um `Response` válido com pipe direto.
 *   - Encerra graciosamente no client disconnect via `req.signal`.
 */
import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TENANT_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;
const SESSION_ID_RE = /^[A-Za-z0-9_\-:.]{1,128}$/;
const DEFAULT_ORG = "default";
const DEFAULT_WS = "default";

function resolveBackendBase(): string {
  const serverSide = process.env.WAKE_API_URL?.trim();
  if (serverSide) return serverSide;
  const browserBase = process.env.NEXT_PUBLIC_WAKE_API_BASE?.trim();
  if (browserBase) return browserBase;
  if (process.env.NODE_ENV !== "production") {
    return "http://localhost:8080";
  }
  throw new Error(
    "SSE proxy misconfigured: set WAKE_API_URL (preferred, server-side) " +
      "or NEXT_PUBLIC_WAKE_API_BASE.",
  );
}

function badRequest(message: string): Response {
  return new Response(JSON.stringify({ error: message }), {
    status: 400,
    headers: { "content-type": "application/json" },
  });
}

interface RouteContext {
  // Next.js 15 entrega `params` como Promise.
  params: Promise<{ id: string }>;
}

export async function GET(req: NextRequest, ctx: RouteContext): Promise<Response> {
  const { id } = await ctx.params;

  if (!id || !SESSION_ID_RE.test(id)) {
    return badRequest("invalid session id");
  }

  const url = new URL(req.url);
  const org = (url.searchParams.get("org") ?? DEFAULT_ORG).trim();
  const ws = (url.searchParams.get("ws") ?? DEFAULT_WS).trim();

  if (!TENANT_RE.test(org)) {
    return badRequest("invalid org");
  }
  if (!TENANT_RE.test(ws)) {
    return badRequest("invalid ws");
  }

  let backend: string;
  try {
    backend = resolveBackendBase();
  } catch (err) {
    return new Response(
      JSON.stringify({
        error: err instanceof Error ? err.message : "backend base unresolved",
      }),
      { status: 500, headers: { "content-type": "application/json" } },
    );
  }

  const upstream = new URL(
    `/v1/sessions/${encodeURIComponent(id)}/stream`,
    backend,
  );

  // Preservar Last-Event-ID quando o browser reconectar.
  const upstreamHeaders: Record<string, string> = {
    Accept: "text/event-stream",
    "X-Wake-Organization-Id": org,
    "X-Wake-Workspace-Id": ws,
  };
  const lastEventId = req.headers.get("last-event-id");
  if (lastEventId) upstreamHeaders["Last-Event-ID"] = lastEventId;

  // API key server-side (env) tem prioridade; cliente pode reforçar via
  // header se quiser (raro — em geral key fica em localStorage e nunca
  // sobe pelo proxy).
  const serverKey = process.env.WAKE_API_KEY;
  if (serverKey) upstreamHeaders["X-Wake-API-Key"] = serverKey;
  const incomingKey = req.headers.get("x-wake-api-key");
  if (incomingKey) upstreamHeaders["X-Wake-API-Key"] = incomingKey;

  // Opcional: forward de `X-Wake-User-Id` para quando RBAC estiver ON
  // (slice A roda em paralelo; integração sem rebreak).
  const userId = req.headers.get("x-wake-user-id");
  if (userId) upstreamHeaders["X-Wake-User-Id"] = userId;

  const started = Date.now();
  // Log estruturado mínimo. Org/ws e session id são identificadores não
  // sensíveis (já passaram pela regex). NUNCA logar headers de auth.
  const sessionDigest = id.length > 12 ? `${id.slice(0, 12)}…` : id;

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstream, {
      method: "GET",
      headers: upstreamHeaders,
      signal: req.signal,
      cache: "no-store",
    });
  } catch (err) {
    // AbortError quando o client fechou — não é falha real.
    const message = err instanceof Error ? err.message : String(err);
    const aborted =
      err instanceof Error &&
      (err.name === "AbortError" || /aborted/i.test(err.message));
    if (aborted) {
      console.info(
        "[sse-proxy] client-disconnect org=%s ws=%s session=%s duration_ms=%d",
        org,
        ws,
        sessionDigest,
        Date.now() - started,
      );
      return new Response(null, { status: 499 });
    }
    console.error(
      "[sse-proxy] upstream-error org=%s ws=%s session=%s err=%s",
      org,
      ws,
      sessionDigest,
      message,
    );
    return new Response(
      JSON.stringify({ error: `upstream unreachable: ${message}` }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }

  if (!upstreamRes.ok || !upstreamRes.body) {
    const text = await upstreamRes.text().catch(() => "");
    console.warn(
      "[sse-proxy] upstream-status %d org=%s ws=%s session=%s",
      upstreamRes.status,
      org,
      ws,
      sessionDigest,
    );
    return new Response(
      text || JSON.stringify({ error: `backend ${upstreamRes.status}` }),
      {
        status: upstreamRes.status,
        headers: { "content-type": "application/json" },
      },
    );
  }

  console.info(
    "[sse-proxy] open org=%s ws=%s session=%s",
    org,
    ws,
    sessionDigest,
  );

  // Repassa o stream bruto. Browsers só aceitam Content-Type
  // `text/event-stream` — forçamos mesmo se upstream não setou.
  return new Response(upstreamRes.body, {
    status: 200,
    headers: {
      "Content-Type": upstreamRes.headers.get("content-type") ?? "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
