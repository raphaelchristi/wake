/**
 * Replay scrubber state machine.
 *
 * Pure reducer + small hook wrapper. The reducer is exported standalone so
 * unit tests can drive it without React. The hook adds the playback timer
 * (auto-advances `currentIndex` on an interval scaled by playback speed).
 */
"use client";

import { useEffect, useReducer } from "react";
import { clampIndex } from "@/lib/replay";
import type { PlaybackSpeed, PlayState } from "@/lib/replay/types";

export interface ReplayState {
  currentIndex: number;
  totalEvents: number;
  playState: PlayState;
  speed: PlaybackSpeed;
}

export type ReplayAction =
  | { type: "SEEK"; index: number }
  | { type: "STEP"; delta: number }
  | { type: "PLAY" }
  | { type: "PAUSE" }
  | { type: "TOGGLE" }
  | { type: "JUMP_START" }
  | { type: "JUMP_END" }
  | { type: "SET_SPEED"; speed: PlaybackSpeed }
  | { type: "SET_TOTAL"; total: number }
  | { type: "TICK" };

export function initReplayState(totalEvents = 0): ReplayState {
  return {
    currentIndex: 0,
    totalEvents,
    playState: "paused",
    speed: 1,
  };
}

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  switch (action.type) {
    case "SEEK":
      return { ...state, currentIndex: clampIndex(action.index, state.totalEvents) };
    case "STEP":
      return {
        ...state,
        currentIndex: clampIndex(state.currentIndex + action.delta, state.totalEvents),
      };
    case "TICK": {
      const next = state.currentIndex + 1;
      if (state.totalEvents === 0) return state;
      // Auto-pause once we land on the last event (next >= last index).
      if (next >= state.totalEvents - 1) {
        return {
          ...state,
          currentIndex: clampIndex(next, state.totalEvents),
          playState: "paused",
        };
      }
      return { ...state, currentIndex: next };
    }
    case "PLAY":
      if (state.totalEvents === 0) return state;
      // If we're at the end, restart from the beginning when user presses play.
      if (state.currentIndex >= state.totalEvents - 1) {
        return { ...state, playState: "playing", currentIndex: 0 };
      }
      return { ...state, playState: "playing" };
    case "PAUSE":
      return { ...state, playState: "paused" };
    case "TOGGLE":
      if (state.playState === "playing") return { ...state, playState: "paused" };
      if (state.totalEvents === 0) return state;
      if (state.currentIndex >= state.totalEvents - 1) {
        return { ...state, playState: "playing", currentIndex: 0 };
      }
      return { ...state, playState: "playing" };
    case "JUMP_START":
      return { ...state, currentIndex: 0 };
    case "JUMP_END":
      return {
        ...state,
        currentIndex: clampIndex(state.totalEvents - 1, state.totalEvents),
        playState: "paused",
      };
    case "SET_SPEED":
      return { ...state, speed: action.speed };
    case "SET_TOTAL": {
      const total = Math.max(0, action.total);
      return {
        ...state,
        totalEvents: total,
        currentIndex: clampIndex(state.currentIndex, total),
      };
    }
    default:
      return state;
  }
}

const TICK_INTERVAL_MS = 250; // 4Hz at 1x; tied to scrubber feel.

/**
 * React hook wrapping the reducer + a setInterval-based ticker.
 *
 * SSR-safe: the interval is only created in the browser. The timer cleans
 * itself up when the component unmounts or `playState` flips to paused.
 */
export function useReplayState(totalEvents: number): {
  state: ReplayState;
  dispatch: React.Dispatch<ReplayAction>;
} {
  const [state, dispatch] = useReducer(replayReducer, initReplayState(totalEvents));

  // Resync `totalEvents` when events load asynchronously.
  useEffect(() => {
    dispatch({ type: "SET_TOTAL", total: totalEvents });
  }, [totalEvents]);

  useEffect(() => {
    if (state.playState !== "playing") return;
    const interval = TICK_INTERVAL_MS / state.speed;
    const id = setInterval(() => {
      dispatch({ type: "TICK" });
    }, interval);
    return () => clearInterval(id);
  }, [state.playState, state.speed]);

  return { state, dispatch };
}
