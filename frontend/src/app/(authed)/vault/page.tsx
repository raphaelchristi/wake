"use client";

import * as React from "react";
import Link from "next/link";
import { Plus, RefreshCcw, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AddCredentialDialog } from "@/components/vault/AddCredentialDialog";
import { CredentialsList } from "@/components/vault/CredentialsList";
import { RotateCredentialDialog } from "@/components/vault/RotateCredentialDialog";
import { useCredentials } from "@/hooks/useCredentials";
import type { VaultCredential } from "@/lib/api/vault-types";

export default function VaultPage() {
  const credentials = useCredentials();
  const [addOpen, setAddOpen] = React.useState(false);
  const [rotateTarget, setRotateTarget] = React.useState<VaultCredential | null>(
    null,
  );

  const handleRevoke = React.useCallback(
    async (cred: VaultCredential) => {
      if (typeof window !== "undefined") {
        const ok = window.confirm(
          `Revoke credential "${cred.name}"? This cannot be undone.`,
        );
        if (!ok) return;
      }
      try {
        await credentials.revoke(cred.vault_id);
      } catch (err) {
        if (typeof window !== "undefined") {
          window.alert(
            `Failed to revoke: ${err instanceof Error ? err.message : "unknown"}`,
          );
        }
      }
    },
    [credentials],
  );

  return (
    <div data-testid="vault-page" className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Vault</h1>
          <p className="text-sm text-muted-foreground">
            Stored credentials. Tokens stay in the vault — only metadata is
            shown here.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void credentials.refresh()}
            disabled={credentials.status === "loading"}
            aria-label="refresh credentials"
          >
            <RefreshCcw
              className={`h-4 w-4 ${credentials.status === "loading" ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            <span className="ml-2">Refresh</span>
          </Button>
          <Link href="/vault/audit">
            <Button variant="outline" size="sm">
              Audit log
            </Button>
          </Link>
          <Button
            size="sm"
            onClick={() => setAddOpen(true)}
            data-testid="open-add-credential"
          >
            <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
            Add credential
          </Button>
        </div>
      </header>

      {credentials.status === "offline" && (
        <Card
          data-testid="vault-offline"
          className="border-amber-500/40 bg-amber-500/5"
        >
          <CardHeader className="flex flex-row items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-500" aria-hidden="true" />
            <CardTitle>Vault offline</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              The backend has no vault adapter configured. Set
              <code className="ml-1 rounded bg-muted px-1 py-0.5 text-xs">
                WAKE_VAULT_URL
              </code>{" "}
              and restart the API; see{" "}
              <Link href="/docs/DASHBOARD" className="underline">
                docs/DASHBOARD.md
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      )}

      {credentials.status === "unauthorized" && (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">Unauthorized</CardTitle>
            <CardDescription>
              Your API key isn’t accepted by the backend. Re-login from{" "}
              <Link href="/login" className="underline">
                /login
              </Link>
              .
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {credentials.status === "error" && credentials.error && (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">
              Failed to load credentials
            </CardTitle>
            <CardDescription>{credentials.error.message}</CardDescription>
          </CardHeader>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Credentials</CardTitle>
          <CardDescription>
            {credentials.credentials.length} stored
          </CardDescription>
        </CardHeader>
        <CardContent>
          <CredentialsList
            credentials={credentials.credentials}
            isLoading={credentials.status === "loading"}
            onRotate={setRotateTarget}
            onRevoke={(c) => void handleRevoke(c)}
          />
        </CardContent>
      </Card>

      <AddCredentialDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        onStart={credentials.startOAuth}
      />
      <RotateCredentialDialog
        credential={rotateTarget}
        open={rotateTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRotateTarget(null);
        }}
        onRotate={credentials.rotate}
      />
    </div>
  );
}
