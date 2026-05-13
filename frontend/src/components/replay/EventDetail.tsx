/**
 * Right-pane event drill-down. Shows header (seq, type, timestamp, parent),
 * a JSON viewer for the payload, and a copy-to-clipboard button.
 *
 * react-json-view-lite is preferred over react-json-view because it ships
 * with zero CSS-in-JS overhead and renders large payloads (megabyte
 * tool_result content blocks) without dropping frames.
 */
"use client";

import * as React from "react";
import { JsonView, defaultStyles } from "react-json-view-lite";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EventTypeBadge } from "./EventTypeBadge";
import type { WakeEvent } from "@/lib/replay/types";

export interface EventDetailProps {
  event: WakeEvent | null;
}

function fmtTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toISOString();
  } catch {
    return ts;
  }
}

export function EventDetail({ event }: EventDetailProps): React.ReactElement {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = React.useCallback(async () => {
    if (!event) return;
    const text = JSON.stringify(event.payload, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — clipboard often unavailable in jsdom / non-https
    }
  }, [event]);

  if (!event) {
    return (
      <div
        data-testid="event-detail-empty"
        className="flex h-full items-center justify-center p-6 text-sm text-slate-500"
      >
        Select an event to inspect its payload.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col" data-testid="event-detail">
      <header className="flex flex-col gap-2 border-b border-slate-200 p-4 dark:border-slate-800">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-slate-500">
              #{event.seq}
            </span>
            <EventTypeBadge type={event.type} />
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleCopy}
            data-testid="btn-copy-payload"
            aria-label="Copy payload as JSON"
          >
            <Copy className="mr-1 h-3.5 w-3.5" />
            {copied ? "Copied" : "Copy JSON"}
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
          <div>
            <span className="font-medium">id</span>{" "}
            <span className="font-mono">{event.id}</span>
          </div>
          <div>
            <span className="font-medium">at</span>{" "}
            <span className="font-mono">{fmtTimestamp(event.created_at)}</span>
          </div>
          {event.parent_id && (
            <div className="col-span-2">
              <span className="font-medium">parent_id</span>{" "}
              <span className="font-mono">{event.parent_id}</span>
            </div>
          )}
        </div>
      </header>
      <div
        data-testid="event-detail-payload"
        className="flex-1 overflow-auto bg-slate-50 p-4 text-xs dark:bg-slate-950"
      >
        <JsonView
          data={event.payload}
          style={defaultStyles}
          shouldExpandNode={(level) => level < 2}
        />
      </div>
    </div>
  );
}
