"use client";

import * as React from "react";
import { KeyRound, RefreshCcw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ProviderIcon } from "@/components/vault/ProviderIcon";
import { formatAbsolute, formatRelative } from "@/lib/format-metrics";
import type { VaultCredential } from "@/lib/api/vault-types";

export interface CredentialsListProps {
  credentials: VaultCredential[];
  isLoading?: boolean;
  onRotate?: (credential: VaultCredential) => void;
  onRevoke?: (credential: VaultCredential) => void;
}

export function CredentialsList({
  credentials,
  isLoading,
  onRotate,
  onRevoke,
}: CredentialsListProps) {
  if (isLoading && credentials.length === 0) {
    return (
      <Table data-testid="credentials-list-loading">
        <TableHeader>
          <TableRow>
            <TableHead>Provider</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Scopes</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Last used</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 3 }).map((_, i) => (
            <TableRow key={i}>
              <TableCell colSpan={6}>
                <div className="h-5 animate-pulse rounded bg-muted/60" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  if (credentials.length === 0) {
    return (
      <div
        role="status"
        data-testid="credentials-list-empty"
        className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-10 text-center"
      >
        <KeyRound className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium">No credentials yet</p>
        <p className="max-w-md text-xs text-muted-foreground">
          Click Add credential to start an OAuth flow for GitHub, Slack, or
          Notion. Tokens never leave the backend — the dashboard only sees
          metadata.
        </p>
      </div>
    );
  }

  return (
    <Table data-testid="credentials-list">
      <TableHeader>
        <TableRow>
          <TableHead>Provider</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Scopes</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Last used</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {credentials.map((cred) => {
          const lastUsed = pickLastUsed(cred);
          return (
            <TableRow key={cred.vault_id} data-testid="credential-row">
              <TableCell>
                <span className="inline-flex items-center gap-2 text-sm">
                  <ProviderIcon provider={cred.provider} />
                  <span className="capitalize">{cred.provider}</span>
                </span>
              </TableCell>
              <TableCell>
                <div className="flex flex-col">
                  <span className="text-sm font-medium">{cred.name}</span>
                  <span
                    className="font-mono text-[10px] text-muted-foreground"
                    title={cred.vault_id}
                  >
                    {cred.vault_id}
                  </span>
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {cred.scopes.length === 0 ? (
                    <Badge variant="outline">no scopes</Badge>
                  ) : (
                    cred.scopes.map((s) => (
                      <Badge key={s} variant="secondary" className="text-[10px]">
                        {s}
                      </Badge>
                    ))
                  )}
                </div>
              </TableCell>
              <TableCell title={formatAbsolute(cred.created_at)}>
                {formatRelative(cred.created_at)}
              </TableCell>
              <TableCell title={lastUsed ? formatAbsolute(lastUsed) : "never"}>
                {formatRelative(lastUsed)}
              </TableCell>
              <TableCell className="text-right">
                <div className="inline-flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onRotate?.(cred)}
                    aria-label={`rotate ${cred.name}`}
                  >
                    <RefreshCcw className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                    Rotate
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onRevoke?.(cred)}
                    aria-label={`revoke ${cred.name}`}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function pickLastUsed(cred: VaultCredential): string | null {
  const raw = cred.metadata?.["last_used_at"] ?? cred.metadata?.["last_used"];
  if (typeof raw === "string") return raw;
  return null;
}
