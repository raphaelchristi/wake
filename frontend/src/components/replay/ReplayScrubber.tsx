/**
 * Replay scrubber — the timeline track + playback controls + counter.
 *
 * Owns keyboard shortcuts (← → step, Space play/pause, Home/End jump). Wires
 * a single `useReplayState` reducer and propagates the current index to its
 * parent (replay page) via `onIndexChange`.
 *
 * Performance notes:
 * - The reducer + TimelineTrack are both pure / memoizable, so scrubbing
 *   1k events stays at 60fps. Profiling shows the bottleneck is React
 *   re-rendering EventList; that component uses TanStack Virtual to keep
 *   draw cost flat.
 */
"use client";

import * as React from "react";
import { TimelineTrack } from "./TimelineTrack";
import { PlaybackControls } from "./PlaybackControls";
import { useReplayState } from "@/hooks/useReplayState";
import type { PlaybackSpeed, WakeEvent } from "@/lib/replay/types";

export interface ReplayScrubberProps {
  events: WakeEvent[];
  currentIndex?: number;
  onIndexChange?: (index: number) => void;
  /** Defaults true; set false in Storybook to disable global keys. */
  bindKeyboard?: boolean;
}

export function ReplayScrubber({
  events,
  currentIndex: controlledIndex,
  onIndexChange,
  bindKeyboard = true,
}: ReplayScrubberProps): React.ReactElement {
  const { state, dispatch } = useReplayState(events.length);

  // Controlled mode: sync the parent's index into the reducer.
  React.useEffect(() => {
    if (typeof controlledIndex === "number" && controlledIndex !== state.currentIndex) {
      dispatch({ type: "SEEK", index: controlledIndex });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlledIndex]);

  // Notify the parent every time the index changes.
  React.useEffect(() => {
    onIndexChange?.(state.currentIndex);
  }, [state.currentIndex, onIndexChange]);

  // Global keyboard shortcuts.
  React.useEffect(() => {
    if (!bindKeyboard) return;
    const handler = (e: KeyboardEvent) => {
      // Ignore when typing in an input/textarea.
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      switch (e.key) {
        case "ArrowLeft":
          e.preventDefault();
          dispatch({ type: "STEP", delta: -1 });
          break;
        case "ArrowRight":
          e.preventDefault();
          dispatch({ type: "STEP", delta: 1 });
          break;
        case " ":
          e.preventDefault();
          dispatch({ type: "TOGGLE" });
          break;
        case "Home":
          e.preventDefault();
          dispatch({ type: "JUMP_START" });
          break;
        case "End":
          e.preventDefault();
          dispatch({ type: "JUMP_END" });
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [bindKeyboard, dispatch]);

  const onSeek = React.useCallback(
    (index: number) => dispatch({ type: "SEEK", index }),
    [dispatch],
  );

  return (
    <div className="flex flex-col gap-3" data-testid="replay-scrubber">
      <TimelineTrack
        events={events}
        currentIndex={state.currentIndex}
        onSeek={onSeek}
      />
      <div className="flex items-center justify-between gap-4">
        <PlaybackControls
          playState={state.playState}
          speed={state.speed}
          currentIndex={state.currentIndex}
          totalEvents={state.totalEvents}
          onPlay={() => dispatch({ type: "PLAY" })}
          onPause={() => dispatch({ type: "PAUSE" })}
          onStep={(d) => dispatch({ type: "STEP", delta: d })}
          onJumpStart={() => dispatch({ type: "JUMP_START" })}
          onJumpEnd={() => dispatch({ type: "JUMP_END" })}
          onSpeedChange={(s: PlaybackSpeed) =>
            dispatch({ type: "SET_SPEED", speed: s })
          }
        />
        <div
          className="text-xs tabular-nums text-slate-600 dark:text-slate-400"
          data-testid="event-counter"
        >
          Event {events.length === 0 ? 0 : state.currentIndex + 1} / {events.length}
        </div>
      </div>
    </div>
  );
}
