"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Waves } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiKey, setApiKey } from "@/lib/auth";

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
  const [error, setError] = useState<string | null>(null);

  // If the operator is already authed, bounce them to `next` immediately.
  useEffect(() => {
    if (getApiKey()) {
      router.replace(next);
    }
  }, [next, router]);

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setError("API key is required.");
      return;
    }
    setApiKey(trimmed);
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
              {error && (
                <p id="api-key-error" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
            <Button type="submit">Sign in</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
