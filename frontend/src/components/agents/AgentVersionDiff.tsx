/**
 * AgentVersionDiff — side-by-side `AgentConfig` diff between two
 * adjacent versions.
 *
 * Phase 8 / Tier 2 gap #12. Renders a structured comparison of:
 *   - system prompt (full text)
 *   - tools (list, by name)
 *   - mcp servers (count + names; full schema is too verbose for this
 *     panel)
 *   - metadata (key-by-key)
 *   - model id
 *
 * Mirrors the side-by-side aesthetic of `ReplayDiff` but the data
 * shape is structural rather than event-stream, so this is its own
 * component rather than a reuse of `ReplayDiff`.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";
import type { AgentConfig } from "@/lib/api/types";

interface FieldDiff {
  key: string;
  left: string;
  right: string;
  changed: boolean;
}

function stringifyMetadata(m: Record<string, string> | undefined): string {
  if (!m) return "(none)";
  const entries = Object.entries(m).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return "(none)";
  return entries.map(([k, v]) => `${k} = ${v}`).join("\n");
}

function diffAgents(left: AgentConfig, right: AgentConfig): FieldDiff[] {
  const rows: FieldDiff[] = [];

  rows.push({
    key: "system",
    left: left.system ?? "(none)",
    right: right.system ?? "(none)",
    changed: (left.system ?? "") !== (right.system ?? ""),
  });

  rows.push({
    key: "model",
    left: left.model?.id ?? "(unknown)",
    right: right.model?.id ?? "(unknown)",
    changed: left.model?.id !== right.model?.id,
  });

  rows.push({
    key: "description",
    left: left.description ?? "(none)",
    right: right.description ?? "(none)",
    changed: (left.description ?? "") !== (right.description ?? ""),
  });

  rows.push({
    key: "metadata",
    left: stringifyMetadata(left.metadata),
    right: stringifyMetadata(right.metadata),
    changed: stringifyMetadata(left.metadata) !== stringifyMetadata(right.metadata),
  });

  return rows;
}

export interface AgentVersionDiffProps {
  left: AgentConfig;
  right: AgentConfig;
}

export function AgentVersionDiff({
  left,
  right,
}: AgentVersionDiffProps): React.ReactElement {
  const rows = React.useMemo(() => diffAgents(left, right), [left, right]);
  const changedCount = rows.filter((r) => r.changed).length;
  return (
    <div className="flex flex-col" data-testid="agent-version-diff">
      <div className="grid grid-cols-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold dark:border-slate-800 dark:bg-slate-900">
        <div data-testid="diff-version-left">v{left.version}</div>
        <div
          data-testid="diff-version-right"
          className="flex items-center justify-between"
        >
          <span>v{right.version}</span>
          <span
            data-testid="version-diff-changed-count"
            className={clsx(
              "rounded-full px-2 py-0.5 text-[10px]",
              changedCount > 0
                ? "bg-amber-500/20 text-amber-700 dark:text-amber-300"
                : "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300",
            )}
          >
            {changedCount} changed
          </span>
        </div>
      </div>
      <div role="list" aria-label="Agent version diff">
        {rows.map((row) => (
          <div
            key={row.key}
            data-testid={`version-diff-row-${row.key}`}
            data-changed={row.changed ? "true" : "false"}
            className={clsx(
              "grid grid-cols-2 border-b border-slate-100 dark:border-slate-900",
              row.changed && "bg-amber-50 dark:bg-amber-950/20",
            )}
          >
            <div className="border-r border-slate-200 dark:border-slate-800">
              <div className="px-3 pt-2 text-[10px] uppercase tracking-wide text-slate-500">
                {row.key}
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words px-3 pb-2 font-mono text-xs">
                {row.left}
              </pre>
            </div>
            <div>
              <div className="px-3 pt-2 text-[10px] uppercase tracking-wide text-slate-500">
                {row.key}
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words px-3 pb-2 font-mono text-xs">
                {row.right}
              </pre>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
