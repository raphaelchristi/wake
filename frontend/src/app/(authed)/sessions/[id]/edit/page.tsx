/**
 * /sessions/[id]/edit — Phase 8 edit-and-replay page.
 *
 * Layout (lg):
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ Header (session id + agent name + back link)                 │
 *   ├──────────────────────────┬───────────────────────────────────┤
 *   │ SessionEditor            │ ReplayDiff                        │
 *   │ (left column)            │ (right column — only after replay)│
 *   └──────────────────────────┴───────────────────────────────────┘
 *
 * The page is *page-shell*: it owns the layout, fetches the source
 * session + source events, drives the replay mutation via
 * `useReplay`, and fetches the replay events when `new_session_id`
 * lands. Heavy lifting lives in the components.
 */
"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { SessionEditor } from "@/components/replay/SessionEditor";
import { ReplayDiff } from "@/components/replay/ReplayDiff";
import { useEvents } from "@/hooks/useEvents";
import { useSession } from "@/hooks/useSession";
import { useReplay, type ReplayOverrides, type ReplayResult } from "@/hooks/useReplay";
import { request } from "@/lib/api/client";
import type { AgentConfig } from "@/lib/api/types";

function useAgent(agentId: string | undefined) {
  return useQuery<AgentConfig>({
    queryKey: ["agent", agentId],
    enabled: Boolean(agentId),
    queryFn: () => request<AgentConfig>("GET", `/v1/agents/${agentId}`),
  });
}

export default function SessionEditPage(): React.ReactElement {
  const params = useParams<{ id: string }>();
  const sessionId = params?.id ?? "";

  const { data: session, error: sessionError } = useSession(sessionId);
  const { data: sourceEvents } = useEvents(sessionId);
  const { data: agent } = useAgent(session?.agent_id);

  const replayMutation = useReplay(sessionId);
  const [replayResult, setReplayResult] = React.useState<ReplayResult | null>(null);
  const { data: replayedEvents } = useEvents(replayResult?.new_session_id);

  const handleReplay = React.useCallback(
    async (overrides: ReplayOverrides) => {
      try {
        const result = await replayMutation.mutateAsync(overrides);
        setReplayResult(result);
      } catch {
        // Error surfaced via replayMutation.error below; swallow here.
      }
    },
    [replayMutation],
  );

  if (sessionError) {
    return (
      <div className="p-6 text-red-600">
        Failed to load session <span className="font-mono">{sessionId}</span>.
      </div>
    );
  }

  const sourceMaxStepsRaw = agent?.metadata?.max_steps;
  const sourceMaxSteps = sourceMaxStepsRaw ? Number.parseInt(sourceMaxStepsRaw, 10) : null;

  return (
    <div
      className="flex h-full flex-col"
      data-testid="session-edit-page"
    >
      <header className="flex items-center justify-between border-b border-slate-200 p-3 dark:border-slate-800">
        <h1 className="text-sm font-medium">
          Edit &amp; replay{" "}
          <span className="font-mono text-slate-500">{sessionId}</span>
          {agent ? (
            <span className="ml-2 text-xs text-slate-400">
              agent {agent.name} (v{agent.version})
            </span>
          ) : null}
        </h1>
        <Link
          href={`/sessions/${sessionId}/replay`}
          className="text-xs text-blue-600 hover:underline dark:text-blue-300"
        >
          ← View original replay
        </Link>
      </header>
      <div className="flex flex-1 min-h-0">
        <aside className="w-1/2 shrink-0 border-r border-slate-200 dark:border-slate-800">
          <SessionEditor
            sourceSystemPrompt={agent?.system ?? null}
            sourceMaxSteps={sourceMaxSteps}
            disabled={replayMutation.isPending}
            onReplay={handleReplay}
          />
          {replayMutation.isError ? (
            <div
              role="alert"
              data-testid="replay-error"
              className="mx-4 mb-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300"
            >
              {replayMutation.error?.message ?? "Replay failed"}
            </div>
          ) : null}
          {replayResult ? (
            <div
              data-testid="replay-summary"
              className="mx-4 mb-4 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300"
            >
              Replayed {replayResult.replayed_event_count} events
              {replayResult.overrides_applied.length > 0 ? (
                <>
                  {" "}
                  with {replayResult.overrides_applied.length} overrides applied
                  ({replayResult.overrides_applied.join(", ")})
                </>
              ) : null}
              .
              <Link
                href={`/sessions/${replayResult.new_session_id}/replay`}
                className="ml-2 underline"
              >
                Open new session →
              </Link>
            </div>
          ) : null}
        </aside>
        <main className="min-w-0 flex-1">
          {replayResult && replayedEvents ? (
            <ReplayDiff
              sourceEvents={sourceEvents ?? []}
              replayEvents={replayedEvents}
              sourceLabel={`Source · ${sessionId.slice(0, 12)}`}
              replayLabel={`Replay · ${replayResult.new_session_id.slice(0, 12)}`}
            />
          ) : (
            <div
              data-testid="replay-empty-state"
              className="flex h-full items-center justify-center p-12 text-sm text-slate-500"
            >
              Submit overrides on the left to see a side-by-side diff here.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
