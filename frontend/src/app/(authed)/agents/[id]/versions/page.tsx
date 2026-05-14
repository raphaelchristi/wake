/**
 * /agents/[id]/versions — Phase 8 agent versioning dashboard.
 *
 * Layout:
 *   ┌────────────────────────────────────────────────────────────┐
 *   │ Header (agent name + latest version)                       │
 *   ├──────────────┬─────────────────────────────────────────────┤
 *   │ Version list │ Adjacent diff (left vs right)               │
 *   │ (timeline)   │ + CanaryControl                             │
 *   └──────────────┴─────────────────────────────────────────────┘
 *
 * Selecting two versions in the timeline drives the diff panel. The
 * canary control acts on the LATEST version (the only version that
 * carries a live canary_weight by contract).
 */
"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { clsx } from "clsx";
import { AgentVersionDiff } from "@/components/agents/AgentVersionDiff";
import { CanaryControl } from "@/components/agents/CanaryControl";
import { useAgentVersions, useApplyCanary } from "@/hooks/useAgentVersions";

function parseCanaryWeight(metadata: Record<string, string> | undefined): number {
  const raw = (metadata ?? {})["canary_weight"];
  if (!raw) return 0;
  const n = Number.parseFloat(raw);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

export default function AgentVersionsPage(): React.ReactElement {
  const params = useParams<{ id: string }>();
  const agentId = params?.id ?? "";

  const { data: versions, isLoading, error } = useAgentVersions(agentId);

  // Default selection: compare second-to-last vs latest.
  const [leftIdx, setLeftIdx] = React.useState<number>(0);
  const [rightIdx, setRightIdx] = React.useState<number>(0);

  React.useEffect(() => {
    if (!versions || versions.length === 0) return;
    const last = versions.length - 1;
    setRightIdx(last);
    setLeftIdx(Math.max(0, last - 1));
  }, [versions]);

  const latest = versions && versions.length > 0 ? versions[versions.length - 1] : undefined;
  const currentWeight = parseCanaryWeight(latest?.metadata);

  const applyCanary = useApplyCanary(agentId, latest?.metadata);

  if (error) {
    return (
      <div className="p-6 text-red-600">
        Failed to load versions for agent{" "}
        <span className="font-mono">{agentId}</span>.
      </div>
    );
  }

  if (isLoading || !versions || !latest) {
    return (
      <div className="flex h-full items-center justify-center p-12 text-sm text-slate-500">
        Loading agent versions…
      </div>
    );
  }

  const left = versions[leftIdx];
  const right = versions[rightIdx];

  return (
    <div className="flex h-full flex-col" data-testid="agent-versions-page">
      <header className="flex items-center justify-between border-b border-slate-200 p-3 dark:border-slate-800">
        <h1 className="text-sm font-medium">
          Versions{" "}
          <span className="font-mono text-slate-500">{latest.name}</span>
          <span className="ml-2 text-xs text-slate-400">
            {versions.length} versions · latest v{latest.version}
          </span>
        </h1>
        <Link
          href={`/agents`}
          className="text-xs text-blue-600 hover:underline dark:text-blue-300"
        >
          ← Back to agents
        </Link>
      </header>
      <div className="flex flex-1 min-h-0">
        <aside
          data-testid="version-timeline"
          className="flex w-72 shrink-0 flex-col overflow-auto border-r border-slate-200 dark:border-slate-800"
        >
          <div className="px-3 py-2 text-[10px] uppercase tracking-wide text-slate-500">
            Timeline (oldest → newest)
          </div>
          {versions.map((v, idx) => {
            const w = parseCanaryWeight(v.metadata);
            const isLeft = idx === leftIdx;
            const isRight = idx === rightIdx;
            return (
              <button
                key={`v-${v.version}`}
                type="button"
                data-testid={`version-row-${v.version}`}
                onClick={() => {
                  // Click cycles: if neither selected → set right; if right
                  // selected and we click another row → set left.
                  if (idx === rightIdx) return;
                  setLeftIdx(rightIdx);
                  setRightIdx(idx);
                }}
                className={clsx(
                  "flex items-start gap-2 border-l-4 px-3 py-2 text-left text-xs transition-colors",
                  isRight
                    ? "border-blue-500 bg-blue-50 dark:bg-blue-950/40"
                    : isLeft
                      ? "border-slate-400 bg-slate-50 dark:bg-slate-900"
                      : "border-transparent hover:bg-slate-50 dark:hover:bg-slate-900",
                )}
              >
                <span className="font-mono tabular-nums text-slate-500">
                  v{v.version}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-slate-700 dark:text-slate-200">
                    {v.description ?? v.system?.slice(0, 60) ?? "(no description)"}
                  </div>
                  <div className="text-[10px] text-slate-400">
                    {new Date(v.updated_at).toLocaleString()}
                  </div>
                </div>
                {w > 0 ? (
                  <span
                    data-testid={`canary-badge-${v.version}`}
                    className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] text-amber-700 dark:text-amber-300"
                  >
                    canary {w}%
                  </span>
                ) : null}
              </button>
            );
          })}
        </aside>
        <main className="flex min-w-0 flex-1 flex-col overflow-auto">
          <div className="border-b border-slate-200 p-4 dark:border-slate-800">
            <CanaryControl
              currentWeight={currentWeight}
              latestVersion={latest.version}
              pending={applyCanary.isPending}
              onApply={(weight) => applyCanary.mutate({ weight })}
            />
            {applyCanary.isError ? (
              <div
                role="alert"
                data-testid="canary-error"
                className="mt-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300"
              >
                {applyCanary.error?.message ?? "Failed to apply canary"}
              </div>
            ) : null}
          </div>
          {left && right ? (
            <AgentVersionDiff left={left} right={right} />
          ) : (
            <div className="p-6 text-sm text-slate-500">
              Select two versions in the timeline to compare.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
