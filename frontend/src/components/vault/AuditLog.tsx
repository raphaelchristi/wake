"use client";

import * as React from "react";
import { ShieldAlert, ShieldCheck, Activity } from "lucide-react";

import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";
import type { AuditEntry } from "@/lib/api/vault-types";

export interface AuditLogProps {
  entries: AuditEntry[];
  isLoading?: boolean;
  offline?: boolean;
  error?: Error | null;
}

const DECISION_VARIANT: Record<
  string,
  "success" | "warning" | "destructive" | "secondary" | "outline"
> = {
  allow: "success",
  oauth_success: "success",
  rotate_started: "secondary",
  oauth_start: "secondary",
  deny: "destructive",
  oauth_failed: "destructive",
  revoked: "warning",
};

export function AuditLog({
  entries,
  isLoading,
  offline,
  error,
}: AuditLogProps) {
  if (offline) {
    return (
      <div
        role="status"
        data-testid="audit-offline"
        className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/5 p-10 text-center"
      >
        <ShieldAlert className="h-6 w-6 text-amber-500" aria-hidden="true" />
        <p className="text-sm font-medium">Vault offline</p>
        <p className="max-w-md text-xs text-muted-foreground">
          The backend has no vault adapter configured, so no audit entries
          can be served. Wire <code>wake_vault_infisical</code> (see
          docs/DASHBOARD.md) and refresh.
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
      >
        Failed to load audit entries: {error.message}
      </div>
    );
  }

  if (isLoading && entries.length === 0) {
    return (
      <Table data-testid="audit-loading">
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Decision</TableHead>
            <TableHead>Provider / host</TableHead>
            <TableHead>Session</TableHead>
            <TableHead>Detail</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 5 }).map((_, i) => (
            <TableRow key={i}>
              <TableCell colSpan={5}>
                <div className="h-5 animate-pulse rounded bg-muted/60" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  if (entries.length === 0) {
    return (
      <div
        role="status"
        data-testid="audit-empty"
        className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-10 text-center"
      >
        <ShieldCheck className="h-6 w-6 text-emerald-500" aria-hidden="true" />
        <p className="text-sm font-medium">No audit entries</p>
        <p className="text-xs text-muted-foreground">
          Activity will appear here as soon as sessions access vault
          credentials.
        </p>
      </div>
    );
  }

  return (
    <Table data-testid="audit-table">
      <TableHeader>
        <TableRow>
          <TableHead>When</TableHead>
          <TableHead>Decision</TableHead>
          <TableHead>Provider / host</TableHead>
          <TableHead>Session</TableHead>
          <TableHead>Detail</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry, idx) => {
          const variant =
            DECISION_VARIANT[entry.decision] ?? "outline";
          return (
            <TableRow
              key={`${entry.timestamp}-${idx}`}
              data-testid="audit-row"
              data-decision={entry.decision}
            >
              <TableCell title={formatAbsolute(entry.timestamp)}>
                <div className="flex items-center gap-2">
                  <Activity className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                  <span>{formatRelative(entry.timestamp)}</span>
                </div>
              </TableCell>
              <TableCell>
                <Badge variant={variant} className={cn(decisionTone(entry.decision))}>
                  {entry.decision}
                </Badge>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  {entry.provider && <ProviderIcon provider={entry.provider} />}
                  <div className="flex flex-col">
                    <span className="capitalize">{entry.provider ?? "—"}</span>
                    {entry.host && (
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {entry.host}
                      </span>
                    )}
                  </div>
                </div>
              </TableCell>
              <TableCell>
                {entry.session_id ? (
                  <a
                    href={`/sessions/${entry.session_id}`}
                    className="font-mono text-[11px] text-primary hover:underline"
                    title={entry.session_id}
                  >
                    {entry.session_id.slice(0, 10)}…
                  </a>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                <span
                  className="line-clamp-1 max-w-[24rem] text-xs text-muted-foreground"
                  title={entry.detail ?? undefined}
                >
                  {entry.detail ?? "—"}
                </span>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function decisionTone(decision: string): string {
  if (decision === "deny" || decision === "oauth_failed") {
    return "uppercase";
  }
  return "";
}
