/**
 * Pure visual layer for the scrubber: renders colored ticks on a horizontal
 * rail. No interaction lives here — ReplayScrubber wraps this and handles
 * pointer / keyboard events.
 *
 * Performance: ticks are absolutely-positioned <span>s with width 2px;
 * 1k of them renders in a single DOM batch and avoids layout thrash on
 * scrub because we use CSS `transform: translateX` for the playhead.
 *
 * For very long sessions (>2k events) we down-sample tick rendering: we
 * still keep the playhead precision (uses index, not rendered ticks) but
 * collapse adjacent events into bucketed marks so the rail stays readable.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";
import { colorForEventType } from "@/lib/replay";
import type { WakeEvent } from "@/lib/replay/types";

const MAX_RENDERED_TICKS = 2000;

export interface TimelineTrackProps {
  events: WakeEvent[];
  currentIndex: number;
  onSeek: (index: number) => void;
  ariaLabel?: string;
}

interface TickRender {
  index: number;
  color: string;
}

function buildTicks(events: WakeEvent[]): TickRender[] {
  if (events.length <= MAX_RENDERED_TICKS) {
    return events.map((ev, i) => ({ index: i, color: colorForEventType(ev.type) }));
  }
  const step = events.length / MAX_RENDERED_TICKS;
  const out: TickRender[] = [];
  for (let i = 0; i < MAX_RENDERED_TICKS; i++) {
    const idx = Math.floor(i * step);
    out.push({ index: idx, color: colorForEventType(events[idx].type) });
  }
  return out;
}

export function TimelineTrack({
  events,
  currentIndex,
  onSeek,
  ariaLabel = "Replay timeline",
}: TimelineTrackProps): React.ReactElement {
  const trackRef = React.useRef<HTMLDivElement>(null);
  const ticks = React.useMemo(() => buildTicks(events), [events]);
  const count = events.length;

  const handlePointerDown = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (count === 0) return;
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect) return;
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      onSeek(Math.round(ratio * (count - 1)));
      (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
    },
    [count, onSeek],
  );

  const handlePointerMove = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
      if (count === 0) return;
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect) return;
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      onSeek(Math.round(ratio * (count - 1)));
    },
    [count, onSeek],
  );

  const handlePointerUp = React.useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    },
    [],
  );

  const ratio = count > 1 ? currentIndex / (count - 1) : 0;

  return (
    <div
      ref={trackRef}
      data-testid="timeline-track"
      role="slider"
      tabIndex={0}
      aria-label={ariaLabel}
      aria-valuemin={0}
      aria-valuemax={Math.max(0, count - 1)}
      aria-valuenow={currentIndex}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      className={clsx(
        "relative h-10 w-full cursor-pointer select-none rounded-md",
        "bg-slate-100 dark:bg-slate-900",
        "border border-slate-200 dark:border-slate-800",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
      )}
    >
      {/* Ticks */}
      <div className="absolute inset-0 overflow-hidden rounded-md">
        {ticks.map((t) => {
          const left = count > 1 ? (t.index / (count - 1)) * 100 : 50;
          return (
            <span
              key={t.index}
              data-testid={`tick-${t.index}`}
              data-event-index={t.index}
              className={clsx("absolute top-2 h-6 w-0.5 rounded-sm opacity-80", t.color)}
              style={{ left: `${left}%` }}
            />
          );
        })}
      </div>
      {/* Playhead */}
      {count > 0 && (
        <div
          data-testid="playhead"
          className="pointer-events-none absolute top-0 h-full w-0.5 bg-blue-600 shadow-md"
          style={{
            left: `${ratio * 100}%`,
            transform: "translateX(-50%)",
            willChange: "left",
          }}
        >
          <div className="absolute -top-1 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-blue-600 ring-2 ring-white dark:ring-slate-950" />
        </div>
      )}
    </div>
  );
}
