"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { SessionStatusBadge } from "@/components/sessions/SessionStatusBadge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSession } from "@/hooks/useSession";
import { durationLabel, relativeTime, shortId } from "@/lib/format";

export default function SessionDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data: session, isPending, error } = useSession(id);

  return (
    <section className="space-y-6">
      <div className="flex items-center gap-2">
        <Link href="/sessions" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          <ArrowLeft className="h-4 w-4" />
          <span>Back to sessions</span>
        </Link>
      </div>

      <header className="space-y-2">
        <h1 className="font-mono text-xl font-semibold tracking-tight">
          {id ? shortId(id) : "Session"}
        </h1>
        {session && <SessionStatusBadge status={session.status} />}
      </header>

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          Failed to load session: {(error as Error).message}
        </div>
      )}

      {isPending && (
        <div className="h-32 w-full animate-pulse rounded-lg bg-muted" aria-label="Loading session details" />
      )}

      {session && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Identifiers</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Field label="Session ID" value={session.id} mono />
              <Field label="Agent" value={`${session.agent_id} (v${session.agent_version})`} mono />
              <Field label="Environment" value={session.environment_id ?? "—"} mono />
              {session.container_id && (
                <Field label="Container" value={session.container_id} mono />
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Lifecycle</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Field label="Status" value={session.status} />
              <Field label="Created" value={`${relativeTime(session.created_at)}`} />
              <Field label="Updated" value={`${relativeTime(session.updated_at)}`} />
              <Field
                label="Duration"
                value={durationLabel(
                  (new Date(session.updated_at).getTime() -
                    new Date(session.created_at).getTime()) /
                    1000,
                )}
              />
            </CardContent>
          </Card>

          {Object.keys(session.metadata ?? {}).length > 0 && (
            <Card className="md:col-span-2">
              <CardHeader>
                <CardTitle>Metadata</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
                  {Object.entries(session.metadata ?? {}).map(([k, v]) => (
                    <div key={k} className="flex flex-col">
                      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                        {k}
                      </dt>
                      <dd className="font-mono text-sm">{v}</dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Card className="border-dashed">
        <CardHeader>
          <CardTitle>Replay</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Event replay UI lives in <code className="font-mono">/sessions/[id]/replay</code> —
          implemented by the <code className="font-mono">dashboard-replay</code> slice.
        </CardContent>
      </Card>
    </section>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={mono ? "font-mono text-xs" : "text-sm"}>{value}</span>
    </div>
  );
}
