/**
 * Play / pause / step / speed buttons. Keyboard shortcuts are wired by
 * ReplayScrubber (parent owns the focus management).
 */
"use client";

import * as React from "react";
import {
  ChevronFirst,
  ChevronLast,
  ChevronLeft,
  ChevronRight,
  Pause,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { PlaybackSpeed, PlayState } from "@/lib/replay/types";

const SPEEDS: PlaybackSpeed[] = [0.5, 1, 2, 5];

export interface PlaybackControlsProps {
  playState: PlayState;
  speed: PlaybackSpeed;
  currentIndex: number;
  totalEvents: number;
  onPlay: () => void;
  onPause: () => void;
  onStep: (delta: number) => void;
  onJumpStart: () => void;
  onJumpEnd: () => void;
  onSpeedChange: (speed: PlaybackSpeed) => void;
}

export function PlaybackControls(props: PlaybackControlsProps): React.ReactElement {
  const {
    playState,
    speed,
    currentIndex,
    totalEvents,
    onPlay,
    onPause,
    onStep,
    onJumpStart,
    onJumpEnd,
    onSpeedChange,
  } = props;
  const playing = playState === "playing";
  const atStart = currentIndex <= 0;
  const atEnd = totalEvents > 0 && currentIndex >= totalEvents - 1;

  return (
    <div className="flex items-center gap-2" data-testid="playback-controls">
      <Button
        size="icon"
        variant="ghost"
        aria-label="Jump to start"
        data-testid="btn-jump-start"
        disabled={atStart}
        onClick={onJumpStart}
      >
        <ChevronFirst className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label="Step back"
        data-testid="btn-step-back"
        disabled={atStart}
        onClick={() => onStep(-1)}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        variant={playing ? "secondary" : "default"}
        aria-label={playing ? "Pause" : "Play"}
        data-testid="btn-play-pause"
        onClick={playing ? onPause : onPlay}
        disabled={totalEvents === 0}
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label="Step forward"
        data-testid="btn-step-forward"
        disabled={atEnd}
        onClick={() => onStep(1)}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label="Jump to end"
        data-testid="btn-jump-end"
        disabled={atEnd}
        onClick={onJumpEnd}
      >
        <ChevronLast className="h-4 w-4" />
      </Button>
      <div className="ml-3 flex items-center gap-1 text-xs text-slate-600 dark:text-slate-400">
        <span className="mr-1">Speed</span>
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            data-testid={`speed-${s}`}
            onClick={() => onSpeedChange(s)}
            className={
              "rounded px-1.5 py-0.5 text-xs " +
              (s === speed
                ? "bg-blue-600 text-white"
                : "bg-transparent hover:bg-slate-100 dark:hover:bg-slate-800")
            }
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}
