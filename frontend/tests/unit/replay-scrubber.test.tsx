/**
 * Component tests for ReplayScrubber. Covers:
 * - tick rendering for each event
 * - playhead position math
 * - keyboard shortcuts
 * - controlled mode (parent passes currentIndex)
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReplayScrubber } from "@/components/replay/ReplayScrubber";
import fixture from "../fixtures/events-fixture.json";
import type { WakeEvent } from "@/lib/replay/types";

const events = (fixture as { data: WakeEvent[] }).data;

describe("ReplayScrubber", () => {
  it("renders one tick per event", () => {
    render(<ReplayScrubber events={events} bindKeyboard={false} />);
    // Sample a few indices.
    expect(screen.getByTestId("tick-0")).toBeInTheDocument();
    expect(screen.getByTestId(`tick-${events.length - 1}`)).toBeInTheDocument();
  });

  it("shows event counter starting at 1/total", () => {
    render(<ReplayScrubber events={events} bindKeyboard={false} />);
    expect(screen.getByTestId("event-counter").textContent).toContain(
      `1 / ${events.length}`,
    );
  });

  it("calls onIndexChange when controlled index changes", () => {
    const onIndexChange = vi.fn();
    const { rerender } = render(
      <ReplayScrubber
        events={events}
        currentIndex={0}
        onIndexChange={onIndexChange}
        bindKeyboard={false}
      />,
    );
    rerender(
      <ReplayScrubber
        events={events}
        currentIndex={5}
        onIndexChange={onIndexChange}
        bindKeyboard={false}
      />,
    );
    expect(onIndexChange).toHaveBeenCalled();
  });

  it("ArrowRight advances index when bound", () => {
    const onIndexChange = vi.fn();
    render(
      <ReplayScrubber
        events={events}
        onIndexChange={onIndexChange}
        bindKeyboard={true}
      />,
    );
    onIndexChange.mockClear();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(onIndexChange).toHaveBeenLastCalledWith(2);
  });

  it("ArrowLeft retreats index", () => {
    const onIndexChange = vi.fn();
    render(
      <ReplayScrubber
        events={events}
        currentIndex={5}
        onIndexChange={onIndexChange}
        bindKeyboard={true}
      />,
    );
    onIndexChange.mockClear();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(onIndexChange).toHaveBeenLastCalledWith(4);
  });

  it("End jumps to last event, Home to first", () => {
    const onIndexChange = vi.fn();
    render(
      <ReplayScrubber
        events={events}
        onIndexChange={onIndexChange}
        bindKeyboard={true}
      />,
    );
    onIndexChange.mockClear();
    fireEvent.keyDown(window, { key: "End" });
    expect(onIndexChange).toHaveBeenLastCalledWith(events.length - 1);
    fireEvent.keyDown(window, { key: "Home" });
    expect(onIndexChange).toHaveBeenLastCalledWith(0);
  });

  it("ignores keys when focus is in an input", () => {
    const onIndexChange = vi.fn();
    render(
      <>
        <input data-testid="input" />
        <ReplayScrubber
          events={events}
          onIndexChange={onIndexChange}
          bindKeyboard={true}
        />
      </>,
    );
    const input = screen.getByTestId("input");
    input.focus();
    onIndexChange.mockClear();
    fireEvent.keyDown(input, { key: "ArrowRight" });
    // Reducer never received the action, so no new index change fired.
    expect(onIndexChange).not.toHaveBeenCalled();
  });

  it("clicking step-forward advances", () => {
    const onIndexChange = vi.fn();
    render(
      <ReplayScrubber
        events={events}
        onIndexChange={onIndexChange}
        bindKeyboard={false}
      />,
    );
    onIndexChange.mockClear();
    fireEvent.click(screen.getByTestId("btn-step-forward"));
    expect(onIndexChange).toHaveBeenLastCalledWith(1);
  });
});
