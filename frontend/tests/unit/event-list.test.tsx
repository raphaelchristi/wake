/**
 * EventList: row rendering, click-to-select, active row highlight.
 *
 * We also verify the summarizer surface for the major event types so that a
 * regression in `summarizeEvent` shows up here.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EventList } from "@/components/replay/EventList";
import { summarizeEvent, colorForEventType } from "@/lib/replay";
import fixture from "../fixtures/events-fixture.json";
import type { WakeEvent } from "@/lib/replay/types";

const events = (fixture as { data: WakeEvent[] }).data;

describe("EventList", () => {
  it("renders a row for every event", () => {
    render(<EventList events={events} currentIndex={0} onSelect={() => undefined} />);
    expect(screen.getByTestId("event-row-0")).toBeInTheDocument();
    expect(screen.getByTestId(`event-row-${events.length - 1}`)).toBeInTheDocument();
  });

  it("invokes onSelect with the row index", () => {
    const onSelect = vi.fn();
    render(<EventList events={events} currentIndex={0} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("event-row-3"));
    expect(onSelect).toHaveBeenCalledWith(3);
  });

  it("highlights the active row", () => {
    render(<EventList events={events} currentIndex={5} onSelect={() => undefined} />);
    const active = screen.getByTestId("event-row-5");
    expect(active.className).toMatch(/bg-blue-50|bg-blue-950/);
  });
});

describe("summarizeEvent", () => {
  it("extracts the first text block from user.message", () => {
    expect(
      summarizeEvent({
        id: "x",
        session_id: "s",
        seq: 0,
        type: "user.message",
        payload: { content: [{ type: "text", text: "hello world" }] },
        created_at: "",
      }),
    ).toContain("hello world");
  });

  it("formats bash tool_use", () => {
    expect(
      summarizeEvent({
        id: "x",
        session_id: "s",
        seq: 0,
        type: "tool_use",
        payload: { name: "bash", input: { command: "ls -la" } },
        created_at: "",
      }),
    ).toContain("ls -la");
  });

  it("flags tool_result errors with [err]", () => {
    expect(
      summarizeEvent({
        id: "x",
        session_id: "s",
        seq: 0,
        type: "tool_result",
        payload: {
          is_error: true,
          content: [{ type: "text", text: "FAILED test" }],
        },
        created_at: "",
      }),
    ).toMatch(/^\[err\]/);
  });

  it("formats status transitions", () => {
    expect(
      summarizeEvent({
        id: "x",
        session_id: "s",
        seq: 0,
        type: "status",
        payload: { from: "idle", to: "running" },
        created_at: "",
      }),
    ).toBe("idle → running");
  });
});

describe("colorForEventType", () => {
  it("maps documented types to expected colors", () => {
    expect(colorForEventType("user.message")).toBe("bg-blue-500");
    expect(colorForEventType("assistant.message")).toBe("bg-green-500");
    expect(colorForEventType("tool_use")).toBe("bg-purple-500");
    expect(colorForEventType("tool_result")).toBe("bg-amber-500");
    expect(colorForEventType("error")).toBe("bg-red-500");
    expect(colorForEventType("vault.access")).toBe("bg-orange-500");
  });

  it("falls back to gray for unknown types", () => {
    expect(colorForEventType("brand.new")).toBe("bg-gray-400");
  });

  it("collapses sandbox.* prefixes to slate", () => {
    expect(colorForEventType("sandbox.provision")).toBe("bg-slate-500");
  });
});
