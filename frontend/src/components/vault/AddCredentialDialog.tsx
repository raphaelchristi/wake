"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { ProviderIcon } from "@/components/vault/ProviderIcon";
import type {
  OAuthStartRequest,
  OAuthStartResponse,
  VaultProvider,
} from "@/lib/api/vault-types";

export interface AddCredentialDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Triggers the OAuth flow and (typically) navigates to the auth URL. */
  onStart: (req: OAuthStartRequest) => Promise<OAuthStartResponse>;
  /** Optional override; defaults to opening the auth URL in a new tab. */
  onAuthorize?: (response: OAuthStartResponse) => void;
}

const PROVIDER_OPTIONS: {
  value: VaultProvider;
  label: string;
  defaultScopes: string;
}[] = [
  { value: "github", label: "GitHub", defaultScopes: "repo,read:user" },
  { value: "slack", label: "Slack", defaultScopes: "chat:write,channels:read" },
  { value: "notion", label: "Notion", defaultScopes: "" },
  { value: "custom", label: "Custom", defaultScopes: "" },
];

/**
 * Dialog that starts an OAuth authorization-code flow against the
 * backend. On success the user is redirected to `response.auth_url`
 * (or the caller-supplied `onAuthorize` handler runs).
 *
 * We persist the in-flight CSRF state into sessionStorage so the
 * /oauth/callback page can correlate. The dialog itself does not see
 * any token — the backend handles the exchange entirely.
 */
export function AddCredentialDialog({
  open,
  onOpenChange,
  onStart,
  onAuthorize,
}: AddCredentialDialogProps) {
  const [provider, setProvider] = React.useState<VaultProvider>("github");
  const [scopes, setScopes] = React.useState<string>(
    PROVIDER_OPTIONS[0]?.defaultScopes ?? "",
  );
  const [redirectUri, setRedirectUri] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const def = PROVIDER_OPTIONS.find((p) => p.value === provider);
    if (def) setScopes(def.defaultScopes);
  }, [provider]);

  const handleStart = React.useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const req: OAuthStartRequest = {
        provider,
        scopes: scopes
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        redirect_uri: redirectUri.trim() || undefined,
      };
      const response = await onStart(req);
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem(
            `wake.oauth.${response.state}`,
            JSON.stringify({
              provider: response.provider,
              auth_url: response.auth_url,
              created_at: new Date().toISOString(),
            }),
          );
        } catch {
          /* sessionStorage best-effort */
        }
      }
      if (onAuthorize) {
        onAuthorize(response);
      } else if (typeof window !== "undefined") {
        window.location.href = response.auth_url;
      }
      onOpenChange(false);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : typeof err === "string"
            ? err
            : "OAuth start failed",
      );
    } finally {
      setSubmitting(false);
    }
  }, [onAuthorize, onOpenChange, onStart, provider, redirectUri, scopes]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add credential</DialogTitle>
          <DialogDescription>
            Start an OAuth Authorization Code flow. After you approve in the
            provider window, the dashboard backend stores the token in the
            vault. The token never reaches your browser.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleStart();
          }}
          data-testid="add-credential-form"
        >
          <div className="space-y-2">
            <Label htmlFor="add-credential-provider">Provider</Label>
            <Select
              id="add-credential-provider"
              data-testid="add-credential-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value as VaultProvider)}
            >
              {PROVIDER_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ProviderIcon provider={provider} />
              <span className="capitalize">{provider}</span>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-credential-scopes">Scopes (comma-separated)</Label>
            <Input
              id="add-credential-scopes"
              data-testid="add-credential-scopes"
              value={scopes}
              placeholder="e.g. repo,read:user"
              onChange={(e) => setScopes(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-credential-redirect">Redirect URI (optional)</Label>
            <Input
              id="add-credential-redirect"
              value={redirectUri}
              placeholder="defaults to env / http://localhost:3000/oauth/callback"
              onChange={(e) => setRedirectUri(e.target.value)}
            />
          </div>

          {error && (
            <p data-testid="add-credential-error" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </form>

        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void handleStart()}
            disabled={submitting}
            data-testid="add-credential-submit"
          >
            {submitting ? "Starting…" : "Start OAuth"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
