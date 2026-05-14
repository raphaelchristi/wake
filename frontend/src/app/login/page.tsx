"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Waves } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiKey, setApiKey } from "@/lib/auth";
import { getTenantScope, setTenantScope } from "@/lib/tenant";

const TENANT_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="h-32 w-full max-w-md animate-pulse rounded-lg bg-muted" />
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params?.get("next") ?? "/sessions";
  const [value, setValue] = useState("");
  const [organizationId, setOrganizationId] = useState("default");
  const [workspaceId, setWorkspaceId] = useState("default");
  const [error, setError] = useState<string | null>(null);

  // Hydrate inputs com o que já estava salvo (caso o usuário esteja
  // re-autenticando depois de logout sem clearTenantScope).
  useEffect(() => {
    const scope = getTenantScope();
    setOrganizationId(scope.organizationId);
    setWorkspaceId(scope.workspaceId);
  }, []);

  // If the operator is already authed, bounce them to `next` immediately.
  useEffect(() => {
    if (getApiKey()) {
      router.replace(next);
    }
  }, [next, router]);

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    const org = organizationId.trim() || "default";
    const ws = workspaceId.trim() || "default";
    if (!trimmed) {
      setError("API key is required.");
      return;
    }
    if (!TENANT_RE.test(org)) {
      setError(
        "Organization id deve casar /^[a-z0-9][a-z0-9_-]{0,62}$/ (minúsculas, hífen ou _).",
      );
      return;
    }
    if (!TENANT_RE.test(ws)) {
      setError(
        "Workspace id deve casar /^[a-z0-9][a-z0-9_-]{0,62}$/ (minúsculas, hífen ou _).",
      );
      return;
    }
    setApiKey(trimmed);
    setTenantScope({ organizationId: org, workspaceId: ws });
    router.replace(next);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
            <Waves className="h-5 w-5 text-primary" aria-hidden="true" />
          </div>
          <CardTitle>Sign in to Wake</CardTitle>
          <CardDescription>
            Enter your Wake API key. It&apos;s stored only in this browser&apos;s localStorage.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={onSubmit}>
            <div className="flex flex-col gap-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="wake_…"
                value={value}
                onChange={(event) => {
                  setValue(event.target.value);
                  setError(null);
                }}
                aria-invalid={error ? "true" : undefined}
                aria-describedby={error ? "api-key-error" : undefined}
                autoFocus
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="organization-id">Organization</Label>
                <Input
                  id="organization-id"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="default"
                  value={organizationId}
                  onChange={(event) => {
                    setOrganizationId(event.target.value);
                    setError(null);
                  }}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="workspace-id">Workspace</Label>
                <Input
                  id="workspace-id"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="default"
                  value={workspaceId}
                  onChange={(event) => {
                    setWorkspaceId(event.target.value);
                    setError(null);
                  }}
                />
              </div>
            </div>
            {error && (
              <p id="api-key-error" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit">Sign in</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
