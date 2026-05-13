"use client";

import * as React from "react";
import { RefreshCcw } from "lucide-react";

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
import { ProviderIcon } from "@/components/vault/ProviderIcon";
import type {
  OAuthStartResponse,
  RotateRequest,
  VaultCredential,
} from "@/lib/api/vault-types";

export interface RotateCredentialDialogProps {
  credential: VaultCredential | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRotate: (
    vaultId: string,
    req: RotateRequest,
  ) => Promise<OAuthStartResponse>;
  onAuthorize?: (response: OAuthStartResponse) => void;
}

/**
 * Confirms rotation of a credential. The backend treats rotate as a
 * "start a fresh OAuth for the same provider/scopes" — the old token
 * stays valid until the callback overwrites it, so in-flight sessions
 * don't break.
 */
export function RotateCredentialDialog({
  credential,
  open,
  onOpenChange,
  onRotate,
  onAuthorize,
}: RotateCredentialDialogProps) {
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [redirectUri, setRedirectUri] = React.useState("");

  React.useEffect(() => {
    if (!open) {
      setSubmitting(false);
      setError(null);
      setRedirectUri("");
    }
  }, [open]);

  const handleRotate = React.useCallback(async () => {
    if (!credential) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await onRotate(credential.vault_id, {
        redirect_uri: redirectUri.trim() || undefined,
      });
      if (typeof window !== "undefined") {
        try {
          window.sessionStorage.setItem(
            `wake.oauth.${response.state}`,
            JSON.stringify({
              provider: response.provider,
              auth_url: response.auth_url,
              rotating_vault_id: credential.vault_id,
              created_at: new Date().toISOString(),
            }),
          );
        } catch {
          /* best-effort */
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
            : "Rotation failed",
      );
    } finally {
      setSubmitting(false);
    }
  }, [credential, onAuthorize, onOpenChange, onRotate, redirectUri]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rotate credential</DialogTitle>
          <DialogDescription>
            Starts a fresh OAuth flow for the same provider and scopes. The
            old token remains valid until the new one replaces it on
            callback, so in-flight sessions keep working.
          </DialogDescription>
        </DialogHeader>

        {credential ? (
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-muted/30 p-3 text-sm">
              <div className="flex items-center gap-2">
                <ProviderIcon provider={credential.provider} />
                <span className="font-medium">{credential.name}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted-foreground">
                <dt>Provider</dt>
                <dd className="capitalize">{credential.provider}</dd>
                <dt>Scopes</dt>
                <dd>{credential.scopes.join(", ") || "none"}</dd>
                <dt>ID</dt>
                <dd className="truncate font-mono" title={credential.vault_id}>
                  {credential.vault_id}
                </dd>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="rotate-redirect">Redirect URI (optional)</Label>
              <Input
                id="rotate-redirect"
                value={redirectUri}
                placeholder="defaults to env / http://localhost:3000/oauth/callback"
                onChange={(e) => setRedirectUri(e.target.value)}
              />
            </div>

            {error && (
              <p data-testid="rotate-error" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No credential selected.</p>
        )}

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
            onClick={() => void handleRotate()}
            disabled={submitting || !credential}
            data-testid="rotate-submit"
          >
            <RefreshCcw className="mr-2 h-4 w-4" aria-hidden="true" />
            {submitting ? "Starting rotation…" : "Rotate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
