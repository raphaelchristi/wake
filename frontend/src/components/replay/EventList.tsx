/**
 * Vertical event list, one row per event. Auto-scrolls the active item into
 * view as the user scrubs.
 *
 * For sessions >500 events we virtualize with @tanstack/react-virtual; under
 * 500 rendering is direct (the overhead of virtualization isn't worth it).
 *
 * Each row is colored by event type via a left-border accent that matches
 * the timeline tick. Active row gets a stronger background highlight so the
 * user always knows where they are on the scrubber.
 */
"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { clsx } from "clsx";
import { colorForEventType, summarizeEvent } from "@/lib/replay";
import type { WakeEvent } from "@/lib/replay/types";

const VIRTUALIZE_THRESHOLD = 500;
const ROW_HEIGHT = 56;

export interface EventListProps {
  events: WakeEvent[];
  currentIndex: number;
  onSelect: (index: number) => void;
}

function Row({
  event,
  index,
  active,
  onClick,
  style,
}: {
  event: WakeEvent;
  index: number;
  active: boolean;
  onClick: () => void;
  style?: React.CSSProperties;
}): React.ReactElement {
  const color = colorForEventType(event.type);
  return (
    <button
      type="button"
      data-testid={`event-row-${index}`}
      data-event-index={index}
      onClick={onClick}
      style={style}
      className={clsx(
        "flex w-full items-start gap-2 border-l-4 px-3 py-2 text-left text-sm transition-colors",
        active
          ? "bg-blue-50 dark:bg-blue-950/40"
          : "hover:bg-slate-50 dark:hover:bg-slate-900",
      )}
    >
      <span
        className={clsx("mt-1 inline-block h-3 w-3 shrink-0 rounded-sm", color)}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span className="font-mono tabular-nums">#{event.seq}</span>
          <span className="font-medium">{event.type}</span>
        </div>
        <div className="truncate text-slate-800 dark:text-slate-200">
          {summarizeEvent(event)}
        </div>
      </div>
    </button>
  );
}

export function EventList({
  events,
  currentIndex,
  onSelect,
}: EventListProps): React.ReactElement {
  const parentRef = React.useRef<HTMLDivElement>(null);
  const shouldVirtualize = events.length >= VIRTUALIZE_THRESHOLD;

  const virtualizer = useVirtualizer({
    count: shouldVirtualize ? events.length : 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  // Scroll active row into view when scrubber moves.
  React.useEffect(() => {
    if (!parentRef.current) return;
    if (shouldVirtualize) {
      virtualizer.scrollToIndex(currentIndex, { align: "center", behavior: "auto" });
      return;
    }
    const el = parentRef.current.querySelector<HTMLElement>(
      `[data-event-index="${currentIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [currentIndex, shouldVirtualize, virtualizer]);

  return (
    <div
      ref={parentRef}
      data-testid="event-list"
      role="listbox"
      aria-label="Session events"
      className="h-full overflow-auto"
    >
      {shouldVirtualize ? (
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            position: "relative",
            width: "100%",
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const event = events[virtualRow.index];
            if (!event) return null;
            return (
              <Row
                key={event.id}
                event={event}
                index={virtualRow.index}
                active={virtualRow.index === currentIndex}
                onClick={() => onSelect(virtualRow.index)}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              />
            );
          })}
        </div>
      ) : (
        events.map((event, index) => (
          <Row
            key={event.id}
            event={event}
            index={index}
            active={index === currentIndex}
            onClick={() => onSelect(index)}
          />
        ))
      )}
    </div>
  );
}
