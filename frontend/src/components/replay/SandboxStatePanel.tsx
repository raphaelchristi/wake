/**
 * Bottom panel: reconstructed sandbox state at the current event seq.
 *
 * Fetches `/v1/sessions/{id}/state-at/{seq}` via TanStack Query and caches
 * forever (snapshots are tied to immutable events). Empty / loading states
 * are explicit so the operator sees something even on a fresh session.
 */
"use client";

import * as React from "react";
import { FileText, FolderTree, Hash, AlertTriangle } from "lucide-react";
import { useStateAt } from "@/hooks/useStateAt";

export interface SandboxStatePanelProps {
  sessionId: string;
  seq: number;
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        {icon}
        {title}
      </div>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  );
}

export function SandboxStatePanel({
  sessionId,
  seq,
}: SandboxStatePanelProps): React.ReactElement {
  const { data, isLoading, error } = useStateAt(sessionId, seq);

  if (error) {
    return (
      <div
        data-testid="sandbox-state-panel"
        className="border-t border-slate-200 p-3 text-sm text-red-600 dark:border-slate-800"
      >
        Failed to load sandbox state.
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div
        data-testid="sandbox-state-panel"
        className="border-t border-slate-200 p-3 text-xs text-slate-500 dark:border-slate-800"
      >
        Reconstructing sandbox state...
      </div>
    );
  }

  const { sandbox, tool_calls_so_far, errors_so_far } = data;

  return (
    <div
      data-testid="sandbox-state-panel"
      className="grid grid-cols-1 gap-4 border-t border-slate-200 p-3 md:grid-cols-4 dark:border-slate-800"
    >
      <Section icon={<FolderTree className="h-3.5 w-3.5" />} title="cwd">
        <code
          data-testid="sandbox-cwd"
          className="break-all rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs dark:bg-slate-900"
        >
          {sandbox.cwd}
        </code>
      </Section>
      <Section
        icon={<FileText className="h-3.5 w-3.5" />}
        title={`Last output (${sandbox.last_output_lines.length} lines)`}
      >
        <pre
          data-testid="sandbox-output"
          className="max-h-24 overflow-auto rounded bg-slate-950 p-2 font-mono text-[11px] leading-tight text-slate-100"
        >
          {sandbox.last_output_lines.join("\n") || "(no output yet)"}
        </pre>
      </Section>
      <Section
        icon={<FileText className="h-3.5 w-3.5" />}
        title={`Files modified (${sandbox.files_modified.length})`}
      >
        <ul
          data-testid="sandbox-files"
          className="max-h-24 overflow-auto text-xs"
        >
          {sandbox.files_modified.length === 0 ? (
            <li className="text-slate-500">(none)</li>
          ) : (
            sandbox.files_modified.map((f) => (
              <li key={f} className="font-mono">
                {f}
              </li>
            ))
          )}
        </ul>
      </Section>
      <Section icon={<Hash className="h-3.5 w-3.5" />} title="Counters">
        <div className="flex gap-3 text-xs">
          <span data-testid="sandbox-tool-calls">
            <Hash className="mr-0.5 inline h-3 w-3" />
            {tool_calls_so_far} tools
          </span>
          <span data-testid="sandbox-errors" className="text-red-600 dark:text-red-400">
            <AlertTriangle className="mr-0.5 inline h-3 w-3" />
            {errors_so_far} errors
          </span>
        </div>
      </Section>
    </div>
  );
}
