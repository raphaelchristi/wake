"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, ShieldAlert, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ProviderIcon } from "@/components/vault/ProviderIcon";

type CallbackState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; provider: string; vault_id: string; name: string }
  | { kind: "error"; message: string };

/**
 * OAuth provider redirects here with `?code=...&state=...`. The page
 * relays the pair to /oauth/callback/api (a Next route handler that
 * proxies the request to the Wake backend) so the browser never
 * directly touches the backend with the user's API key from the URL.
 *
 * The CSRF state previously written into sessionStorage by the
 * Add/Rotate dialog is consumed here to give the user provider
 * context while the round-trip is in flight.
 */
export default function OAuthCallbackPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [state, setState] = React.useState<CallbackState>({ kind: "idle" });
  const [providerHint, setProviderHint] = React.useState<string | null>(null);

  const code = params.get("code");
  const csrf = params.get("state");
  const errorParam = params.get("error");
  const errorDescription = params.get("error_description");

  React.useEffect(() => {
    if (!csrf) return;
    if (typeof window === "undefined") return;
    try {
      const raw = window.sessionStorage.getItem(`wake.oauth.${csrf}`);
      if (raw) {
        const parsed = JSON.parse(raw) as { provider?: string };
        if (parsed.provider) setProviderHint(parsed.provider);
      }
    } catch {
      /* ignore */
    }
  }, [csrf]);

  React.useEffect(() => {
    if (errorParam) {
      setState({
        kind: "error",
        message: errorDescription ?? errorParam,
      });
      return;
    }
    if (!code || !csrf) {
      setState({
        kind: "error",
        message: "missing 'code' or 'state' query parameter",
      });
      return;
    }
    setState({ kind: "loading" });
    void (async () => {
      try {
        const res = await fetch("/oauth/callback/api", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, state: csrf }),
        });
        const data = (await res.json().catch(() => null)) as {
          error?: string;
          provider?: string;
          vault_id?: string;
          name?: string;
        } | null;
        if (!res.ok || !data || data.error) {
          setState({
            kind: "error",
            message:
              data?.error ?? `backend returned ${res.status}`,
          });
          return;
        }
        if (typeof window !== "undefined") {
          try {
            window.sessionStorage.removeItem(`wake.oauth.${csrf}`);
          } catch {
            /* ignore */
          }
        }
        setState({
          kind: "success",
          provider: data.provider ?? providerHint ?? "custom",
          vault_id: data.vault_id ?? "",
          name: data.name ?? "",
        });
      } catch (err) {
        setState({
          kind: "error",
          message:
            err instanceof Error
              ? err.message
              : "Network error during OAuth callback",
        });
      }
    })();
  }, [code, csrf, errorDescription, errorParam, providerHint]);

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-6 p-6">
      <Card>
        <CardHeader>
          <CardTitle>OAuth callback</CardTitle>
          <CardDescription>
            Completing the authorization flow.{" "}
            {providerHint && (
              <span className="inline-flex items-center gap-1 capitalize">
                <ProviderIcon provider={providerHint} /> {providerHint}
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {state.kind === "loading" && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Exchanging code with the backend…
            </div>
          )}
          {state.kind === "error" && (
            <div
              data-testid="oauth-callback-error"
              className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
            >
              <div className="flex items-center gap-2 font-medium">
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                Callback failed
              </div>
              <p className="mt-1 text-xs">{state.message}</p>
            </div>
          )}
          {state.kind === "success" && (
            <div
              data-testid="oauth-callback-success"
              className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm"
            >
              <div className="flex items-center gap-2 font-medium text-emerald-600">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                Credential stored
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted-foreground">
                <dt>Provider</dt>
                <dd className="capitalize">{state.provider}</dd>
                <dt>Name</dt>
                <dd className="font-mono">{state.name}</dd>
                <dt>Vault ID</dt>
                <dd className="truncate font-mono" title={state.vault_id}>
                  {state.vault_id}
                </dd>
              </dl>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => router.back()}>
          Back
        </Button>
        <Link href="/vault">
          <Button variant="default">View vault</Button>
        </Link>
      </div>
    </div>
  );
}
