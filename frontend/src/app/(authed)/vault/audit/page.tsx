"use client";

import * as React from "react";
import Link from "next/link";
import { RefreshCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { AuditLog } from "@/components/vault/AuditLog";
import { useAudit } from "@/hooks/useAudit";

const DECISION_OPTIONS = [
  { value: "", label: "All decisions" },
  { value: "allow", label: "allow" },
  { value: "deny", label: "deny" },
  { value: "oauth_start", label: "oauth_start" },
  { value: "oauth_success", label: "oauth_success" },
  { value: "oauth_failed", label: "oauth_failed" },
  { value: "rotate_started", label: "rotate_started" },
  { value: "revoked", label: "revoked" },
];

export default function VaultAuditPage() {
  const [provider, setProvider] = React.useState("");
  const [host, setHost] = React.useState("");
  const [decision, setDecision] = React.useState("");
  const [limit, setLimit] = React.useState(200);

  const audit = useAudit({
    provider: provider || null,
    host: host || null,
    decision: decision || null,
    limit,
    autoRefreshMs: 30_000,
  });

  return (
    <div data-testid="vault-audit-page" className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
          <p className="text-sm text-muted-foreground">
            Every vault access (allow/deny/oauth/rotate/revoke) emitted by
            the Wake backend in this process. Auto-refreshes every 30s.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/vault">
            <Button variant="outline" size="sm">
              Back to vault
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void audit.refresh()}
            aria-label="refresh audit"
          >
            <RefreshCcw className="h-4 w-4" aria-hidden="true" />
            <span className="ml-2">Refresh</span>
          </Button>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            Filter server-side; results refresh on change.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
            <div className="space-y-1">
              <Label htmlFor="audit-provider">Provider</Label>
              <Input
                id="audit-provider"
                value={provider}
                placeholder="github / slack / notion"
                onChange={(e) => setProvider(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-host">Host</Label>
              <Input
                id="audit-host"
                value={host}
                placeholder="api.github.com"
                onChange={(e) => setHost(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-decision">Decision</Label>
              <Select
                id="audit-decision"
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
              >
                {DECISION_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="audit-limit">Limit</Label>
              <Input
                id="audit-limit"
                type="number"
                min={1}
                max={1000}
                value={limit}
                onChange={(e) => {
                  const n = Number.parseInt(e.target.value, 10);
                  setLimit(Number.isFinite(n) ? Math.max(1, Math.min(1000, n)) : 200);
                }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Entries</CardTitle>
          <CardDescription>
            {audit.entries.length} matching · limit {limit}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AuditLog
            entries={audit.entries}
            isLoading={audit.isLoading}
            offline={audit.offline}
            error={audit.error}
          />
        </CardContent>
      </Card>
    </div>
  );
}
