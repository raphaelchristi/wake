/**
 * Colored pill for an event type. Consumed by EventList rows + EventDetail
 * header.
 */
"use client";

import * as React from "react";
import { clsx } from "clsx";
import { colorForEventType } from "@/lib/replay";

export interface EventTypeBadgeProps {
  type: string;
  className?: string;
}

export function EventTypeBadge({ type, className }: EventTypeBadgeProps): React.ReactElement {
  const bg = colorForEventType(type);
  return (
    <span
      data-testid={`event-type-badge-${type}`}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-white",
        bg,
        className,
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-white/80" aria-hidden />
      {type}
    </span>
  );
}
