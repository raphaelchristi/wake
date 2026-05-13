/**
 * Pure-reducer tests for the replay scrubber state machine.
 *
 * No React mount required — the hook layer is tested via the component
 * tests. Here we lock in deterministic behavior of the reducer.
 */
import { describe, it, expect } from "vitest";
import {
  initReplayState,
  replayReducer,
  type ReplayAction,
  type ReplayState,
} from "@/hooks/useReplayState";

function run(initial: ReplayState, actions: ReplayAction[]): ReplayState {
  return actions.reduce(replayReducer, initial);
}

describe("replayReducer", () => {
  it("initializes paused at index 0", () => {
    const s = initReplayState(10);
    expect(s.currentIndex).toBe(0);
    expect(s.playState).toBe("paused");
    expect(s.speed).toBe(1);
    expect(s.totalEvents).toBe(10);
  });

  it("SEEK clamps to bounds", () => {
    const s = initReplayState(5);
    expect(replayReducer(s, { type: "SEEK", index: 3 }).currentIndex).toBe(3);
    expect(replayReducer(s, { type: "SEEK", index: -1 }).currentIndex).toBe(0);
    expect(replayReducer(s, { type: "SEEK", index: 99 }).currentIndex).toBe(4);
  });

  it("STEP increments / decrements with clamping", () => {
    const s = initReplayState(3);
    const after = run(s, [{ type: "STEP", delta: 1 }, { type: "STEP", delta: 1 }]);
    expect(after.currentIndex).toBe(2);
    const overshoot = replayReducer(after, { type: "STEP", delta: 5 });
    expect(overshoot.currentIndex).toBe(2);
    const backwards = run(overshoot, [{ type: "STEP", delta: -10 }]);
    expect(backwards.currentIndex).toBe(0);
  });

  it("TICK advances and auto-pauses at end", () => {
    let s = initReplayState(2);
    s = replayReducer(s, { type: "PLAY" });
    expect(s.playState).toBe("playing");
    s = replayReducer(s, { type: "TICK" });
    expect(s.currentIndex).toBe(1);
    expect(s.playState).toBe("paused");
  });

  it("PLAY from end restarts from 0", () => {
    let s = initReplayState(3);
    s = replayReducer(s, { type: "JUMP_END" });
    expect(s.currentIndex).toBe(2);
    s = replayReducer(s, { type: "PLAY" });
    expect(s.currentIndex).toBe(0);
    expect(s.playState).toBe("playing");
  });

  it("TOGGLE alternates play/pause", () => {
    let s = initReplayState(5);
    s = replayReducer(s, { type: "TOGGLE" });
    expect(s.playState).toBe("playing");
    s = replayReducer(s, { type: "TOGGLE" });
    expect(s.playState).toBe("paused");
  });

  it("JUMP_START and JUMP_END move to bounds", () => {
    let s = initReplayState(5);
    s = replayReducer(s, { type: "JUMP_END" });
    expect(s.currentIndex).toBe(4);
    s = replayReducer(s, { type: "JUMP_START" });
    expect(s.currentIndex).toBe(0);
  });

  it("JUMP_END pauses playback", () => {
    let s = initReplayState(5);
    s = replayReducer(s, { type: "PLAY" });
    s = replayReducer(s, { type: "JUMP_END" });
    expect(s.playState).toBe("paused");
  });

  it("SET_SPEED updates speed only", () => {
    const s = initReplayState(5);
    const next = replayReducer(s, { type: "SET_SPEED", speed: 2 });
    expect(next.speed).toBe(2);
    expect(next.currentIndex).toBe(0);
  });

  it("SET_TOTAL adjusts and re-clamps currentIndex", () => {
    let s = initReplayState(10);
    s = replayReducer(s, { type: "SEEK", index: 7 });
    s = replayReducer(s, { type: "SET_TOTAL", total: 3 });
    expect(s.totalEvents).toBe(3);
    expect(s.currentIndex).toBe(2);
  });

  it("PLAY with 0 events is no-op", () => {
    const s = initReplayState(0);
    const after = replayReducer(s, { type: "PLAY" });
    expect(after.playState).toBe("paused");
  });
});
