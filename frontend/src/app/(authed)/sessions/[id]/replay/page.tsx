/**
 * /sessions/[id]/replay — the replay view.
 *
 * Layout (lg):
 *   ┌────────────────────────────────────────┐
 *   │ Header (session id)                    │
 *   ├──────────────┬─────────────────────────┤
 *   │ EventList    │ EventDetail             │
 *   ├──────────────┴─────────────────────────┤
 *   │ SandboxStatePanel                      │
 *   ├────────────────────────────────────────┤
 *   │ ReplayScrubber (timeline + controls)   │
 *   └────────────────────────────────────────┘
 *
 * The shell slice owns auth via the (authed) layout. This page assumes the
 * user is authenticated when it runs.
 */
"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { EventList } from "@/components/replay/EventList";
import { EventDetail } from "@/components/replay/EventDetail";
import { SandboxStatePanel } from "@/components/replay/SandboxStatePanel";
import { ReplayScrubber } from "@/components/replay/ReplayScrubber";
import { useEvents } from "@/hooks/useEvents";

export default function ReplayPage(): React.ReactElement {
  const params = useParams<{ id: string }>();
  const sessionId = params?.id ?? "";
  const { data: events, isLoading, error } = useEvents(sessionId);
  const [currentIndex, setCurrentIndex] = React.useState(0);

  if (error) {
    return (
      <div className="p-6 text-red-600">
        Failed to load events for session{" "}
        <span className="font-mono">{sessionId}</span>.
      </div>
    );
  }

  if (isLoading || !events) {
    return (
      <div className="flex h-full items-center justify-center p-12 text-sm text-slate-500">
        Loading session...
      </div>
    );
  }

  const currentEvent = events[currentIndex] ?? null;
  const currentSeq = currentEvent?.seq ?? 0;

  return (
    <div className="flex h-full flex-col" data-testid="replay-page">
      <header className="border-b border-slate-200 p-3 dark:border-slate-800">
        <h1 className="text-sm font-medium">
          Replay <span className="font-mono text-slate-500">{sessionId}</span>
          <span className="ml-2 text-xs text-slate-400">
            {events.length} events
          </span>
        </h1>
      </header>
      <div className="flex flex-1 min-h-0">
        <aside className="w-80 shrink-0 border-r border-slate-200 dark:border-slate-800">
          <EventList
            events={events}
            currentIndex={currentIndex}
            onSelect={setCurrentIndex}
          />
        </aside>
        <main className="min-w-0 flex-1">
          <EventDetail event={currentEvent} />
        </main>
      </div>
      {events.length > 0 && sessionId ? (
        <SandboxStatePanel sessionId={sessionId} seq={currentSeq} />
      ) : null}
      <footer className="border-t border-slate-200 p-3 dark:border-slate-800">
        <ReplayScrubber
          events={events}
          currentIndex={currentIndex}
          onIndexChange={setCurrentIndex}
        />
      </footer>
    </div>
  );
}
