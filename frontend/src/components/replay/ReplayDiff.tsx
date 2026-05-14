/**
 * ReplayDiff — side-by-side event scrubber comparing source vs replay.
 *
 * Phase 8 / Tier 2 gap #10. Renders two columns of events stacked
 * row-by-row indexed by `seq`. When the two event payloads diverge we
 * highlight the row; identical rows render muted so the operator can
 * scan for the diff hotspots without parsing every line.
 *
 * The diff algorithm is intentionally simple: events are aligned by
 * **sequence number** (the replay engine copies the source log so
 * counts match modulo truncation). When the replay is shorter than the
 * source (max_steps truncation) we render "—" on the missing side.
 *
 * This is NOT a full text diff — payloads are summarised via the same
 * `summarizeEvent` helper the EventList uses. Operators wanting a
 * deeper inspection click a row and the parent page opens the
 * EventDetail panel.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";
import { colorForEventType, summarizeEvent } from "@/lib/replay";
import type { WakeEvent } from "@/lib/replay/types";

export interface DiffRow {
  seq: number;
  source: WakeEvent | null;
  replay: WakeEvent | null;
  changed: boolean;
}

/**
 * Align two event lists by `seq` (already sorted ascending by the
 * `useEvents` hook). Pads the shorter side with `null` so the renderer
 * can flag missing rows.
 *
 * Marks a row as `changed` when:
 *   - one side is null (truncation / new event)
 *   - the event types differ
 *   - the JSON-serialised payloads differ
 */
export function alignEvents(
  source: WakeEvent[],
  replay: WakeEvent[],
): DiffRow[] {
  const rows: DiffRow[] = [];
  const length = Math.max(source.length, replay.length);
  for (let i = 0; i < length; i++) {
    const s = source[i] ?? null;
    const r = replay[i] ?? null;
    let changed = false;
    if (s === null || r === null) {
      changed = true;
    } else if (s.type !== r.type) {
      changed = true;
    } else {
      try {
        changed = JSON.stringify(s.payload) !== JSON.stringify(r.payload);
      } catch {
        // Defensive: if payload has cycles we treat as changed.
        changed = true;
      }
    }
    rows.push({
      seq: s?.seq ?? r?.seq ?? i,
      source: s,
      replay: r,
      changed,
    });
  }
  return rows;
}

interface CellProps {
  event: WakeEvent | null;
  active: boolean;
  onClick: () => void;
}

function Cell({ event, active, onClick }: CellProps): React.ReactElement {
  if (event === null) {
    return (
      <div
        className={clsx(
          "flex items-center px-3 py-2 text-xs text-slate-400 italic",
          active && "bg-blue-50 dark:bg-blue-950/40",
        )}
      >
        — (missing)
      </div>
    );
  }
  const color = colorForEventType(event.type);
  return (
    <button
      type="button"
      data-testid={`diff-cell-${event.session_id}-${event.seq}`}
      onClick={onClick}
      className={clsx(
        "flex w-full items-start gap-2 border-l-4 px-3 py-2 text-left text-xs transition-colors",
        active
          ? "bg-blue-50 dark:bg-blue-950/40"
          : "hover:bg-slate-50 dark:hover:bg-slate-900",
      )}
    >
      <span
        className={clsx("mt-1 inline-block h-2 w-2 shrink-0 rounded-sm", color)}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wide text-slate-500">
          {event.type}
        </div>
        <div className="truncate text-slate-800 dark:text-slate-200">
          {summarizeEvent(event)}
        </div>
      </div>
    </button>
  );
}

export interface ReplayDiffProps {
  sourceEvents: WakeEvent[];
  replayEvents: WakeEvent[];
  /** Index into the aligned diff rows the parent considers "active". */
  currentIndex?: number;
  onSelect?: (index: number, row: DiffRow) => void;
  /** Display labels for the column headers. */
  sourceLabel?: string;
  replayLabel?: string;
}

export function ReplayDiff({
  sourceEvents,
  replayEvents,
  currentIndex = 0,
  onSelect,
  sourceLabel = "Source",
  replayLabel = "Replay",
}: ReplayDiffProps): React.ReactElement {
  const rows = React.useMemo(
    () => alignEvents(sourceEvents, replayEvents),
    [sourceEvents, replayEvents],
  );
  const changedCount = rows.filter((r) => r.changed).length;

  return (
    <div className="flex h-full flex-col" data-testid="replay-diff">
      <div className="grid grid-cols-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold dark:border-slate-800 dark:bg-slate-900">
        <div data-testid="diff-header-source">
          {sourceLabel}{" "}
          <span className="ml-2 font-normal text-slate-500">
            {sourceEvents.length} events
          </span>
        </div>
        <div data-testid="diff-header-replay" className="flex justify-between">
          <span>
            {replayLabel}{" "}
            <span className="ml-2 font-normal text-slate-500">
              {replayEvents.length} events
            </span>
          </span>
          <span
            data-testid="diff-changed-count"
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
      <div
        role="list"
        aria-label="Side-by-side event diff"
        className="flex-1 overflow-auto"
      >
        {rows.map((row, idx) => (
          <div
            key={`${row.seq}-${idx}`}
            data-testid={`diff-row-${idx}`}
            data-changed={row.changed ? "true" : "false"}
            className={clsx(
              "grid grid-cols-2 border-b border-slate-100 dark:border-slate-900",
              row.changed && "bg-amber-50 dark:bg-amber-950/20",
            )}
          >
            <Cell
              event={row.source}
              active={idx === currentIndex}
              onClick={() => onSelect?.(idx, row)}
            />
            <div className="border-l border-slate-200 dark:border-slate-800">
              <Cell
                event={row.replay}
                active={idx === currentIndex}
                onClick={() => onSelect?.(idx, row)}
              />
            </div>
          </div>
        ))}
        {rows.length === 0 ? (
          <div
            data-testid="diff-empty"
            className="px-3 py-6 text-center text-sm text-slate-500"
          >
            No events to compare.
          </div>
        ) : null}
      </div>
    </div>
  );
}
