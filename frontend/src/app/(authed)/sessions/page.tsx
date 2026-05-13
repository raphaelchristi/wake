"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import { SessionFilters, parseFilters } from "@/components/sessions/SessionFilters";
import { SessionsTable } from "@/components/sessions/SessionsTable";
import { Button } from "@/components/ui/button";
import { useSessions } from "@/hooks/useSessions";
import { WakeApiError } from "@/lib/api/client";
import type { SessionListQuery, SessionStatus } from "@/lib/api/types";

const PAGE_SIZE = 50;

function buildQuery(search: URLSearchParams): SessionListQuery {
  const filters = parseFilters(search);
  const pageRaw = Number(search.get("page") ?? 1);
  const page = Number.isFinite(pageRaw) && pageRaw > 0 ? pageRaw : 1;
  return {
    agent: filters.agent || undefined,
    status: (filters.status || undefined) as SessionStatus | undefined,
    model: filters.model || undefined,
    since: filters.since || undefined,
    until: filters.until || undefined,
    q: filters.q || undefined,
    page,
    page_size: PAGE_SIZE,
  };
}

export default function SessionsPage() {
  return (
    <Suspense fallback={<SessionsListFallback />}>
      <SessionsListView />
    </Suspense>
  );
}

function SessionsListFallback() {
  return (
    <div className="space-y-4">
      <div className="h-7 w-40 animate-pulse rounded bg-muted" />
      <div className="h-9 w-full animate-pulse rounded bg-muted" />
      <div className="h-72 w-full animate-pulse rounded-lg bg-muted" />
    </div>
  );
}

function SessionsListView() {
  const search = useSearchParams();
  const router = useRouter();
  const query = useMemo(
    () => buildQuery(new URLSearchParams(search?.toString() ?? "")),
    [search],
  );

  const result = useSessions(query);
  const sessions = result.data?.data ?? [];
  const page = query.page ?? 1;
  const hasMore = sessions.length === PAGE_SIZE;

  const isAuthError = result.error instanceof WakeApiError && result.error.isAuthError;

  function goToPage(next: number) {
    const params = new URLSearchParams(search?.toString() ?? "");
    if (next <= 1) params.delete("page");
    else params.set("page", String(next));
    const qs = params.toString();
    router.replace(`/sessions${qs ? `?${qs}` : ""}`);
  }

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Sessions</h1>
        <p className="text-sm text-muted-foreground">
          {result.isFetching ? "Refreshing…" : `${sessions.length} on this page`}
        </p>
      </div>

      <SessionFilters />

      {isAuthError ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          Your API key was rejected. <a className="underline" href="/login">Sign in again</a>.
        </div>
      ) : result.error ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          Failed to load sessions: {(result.error as Error).message}
        </div>
      ) : null}

      <SessionsTable sessions={sessions} isLoading={result.isPending} />

      <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground">
        <span>Page {page}</span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => goToPage(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!hasMore}
            onClick={() => goToPage(page + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </section>
  );
}
