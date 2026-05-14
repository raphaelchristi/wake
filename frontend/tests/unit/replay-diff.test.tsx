/**
 * Component + pure-function tests for ReplayDiff.
 *
 * Locks in:
 *  - alignEvents pads the shorter side and flags missing rows as changed
 *  - rows render with both columns, changed rows carry data-changed=true
 *  - header counts reflect source/replay sizes + changed count
 *  - empty state when both lists are empty
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReplayDiff, alignEvents } from "@/components/replay/ReplayDiff";
import type { WakeEvent } from "@/lib/replay/types";

function makeEvent(
  seq: number,
  type: WakeEvent["type"],
  payload: Record<string, unknown> = {},
  sessionId = "sess_src",
): WakeEvent {
  return {
    id: `${sessionId}-evt-${seq}`,
    session_id: sessionId,
    seq,
    type,
    payload,
    parent_id: null,
    metadata: null,
    created_at: new Date(0).toISOString(),
    organization_id: "default",
    workspace_id: "default",
  };
}

describe("alignEvents", () => {
  it("returns empty rows when both lists are empty", () => {
    expect(alignEvents([], [])).toEqual([]);
  });

  it("aligns equal-length lists and marks unchanged rows", () => {
    const src = [
      makeEvent(0, "user.message", { content: "hi" }),
      makeEvent(1, "assistant.message", { content: "hello" }),
    ];
    const rep = [
      makeEvent(0, "user.message", { content: "hi" }, "sess_rep"),
      makeEvent(1, "assistant.message", { content: "hello" }, "sess_rep"),
    ];
    const rows = alignEvents(src, rep);
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => !r.changed)).toBe(true);
  });

  it("flags rows with different payloads as changed", () => {
    const src = [makeEvent(0, "user.message", { content: "hi" })];
    const rep = [makeEvent(0, "user.message", { content: "HELLO" }, "sess_rep")];
    const [row] = alignEvents(src, rep);
    expect(row?.changed).toBe(true);
  });

  it("flags rows with different event types as changed", () => {
    const src = [makeEvent(0, "user.message", { content: "hi" })];
    const rep = [makeEvent(0, "assistant.message", { content: "hi" }, "sess_rep")];
    const [row] = alignEvents(src, rep);
    expect(row?.changed).toBe(true);
  });

  it("pads the shorter side with null and flags as changed (truncation)", () => {
    const src = [
      makeEvent(0, "user.message"),
      makeEvent(1, "assistant.message"),
      makeEvent(2, "tool_use"),
    ];
    const rep = [makeEvent(0, "user.message", {}, "sess_rep")];
    const rows = alignEvents(src, rep);
    expect(rows).toHaveLength(3);
    expect(rows[0]?.changed).toBe(false);
    expect(rows[1]?.changed).toBe(true);
    expect(rows[1]?.replay).toBeNull();
    expect(rows[2]?.replay).toBeNull();
  });

  it("pads the source side when replay is longer", () => {
    const src = [makeEvent(0, "user.message")];
    const rep = [
      makeEvent(0, "user.message", {}, "sess_rep"),
      makeEvent(1, "assistant.message", {}, "sess_rep"),
    ];
    const rows = alignEvents(src, rep);
    expect(rows).toHaveLength(2);
    expect(rows[1]?.source).toBeNull();
    expect(rows[1]?.changed).toBe(true);
  });
});

describe("<ReplayDiff />", () => {
  it("renders empty state when both lists are empty", () => {
    render(<ReplayDiff sourceEvents={[]} replayEvents={[]} />);
    expect(screen.getByTestId("diff-empty")).toBeInTheDocument();
  });

  it("renders side-by-side headers with counts", () => {
    const src = [makeEvent(0, "user.message")];
    const rep = [makeEvent(0, "user.message", {}, "sess_rep")];
    render(<ReplayDiff sourceEvents={src} replayEvents={rep} />);
    expect(screen.getByTestId("diff-header-source").textContent).toContain(
      "1 events",
    );
    expect(screen.getByTestId("diff-header-replay").textContent).toContain(
      "1 events",
    );
    expect(screen.getByTestId("diff-changed-count").textContent).toContain(
      "0 changed",
    );
  });

  it("renders one row per aligned event and marks changed rows", () => {
    const src = [
      makeEvent(0, "user.message", { content: "hi" }),
      makeEvent(1, "assistant.message", { content: "hello" }),
    ];
    const rep = [
      makeEvent(0, "user.message", { content: "hi" }, "sess_rep"),
      makeEvent(1, "assistant.message", { content: "WORLD" }, "sess_rep"),
    ];
    render(<ReplayDiff sourceEvents={src} replayEvents={rep} />);
    expect(screen.getByTestId("diff-row-0").getAttribute("data-changed")).toBe(
      "false",
    );
    expect(screen.getByTestId("diff-row-1").getAttribute("data-changed")).toBe(
      "true",
    );
    expect(screen.getByTestId("diff-changed-count").textContent).toContain(
      "1 changed",
    );
  });

  it("invokes onSelect when a cell is clicked", () => {
    const onSelect = vi.fn();
    const src = [makeEvent(0, "user.message", { content: "hi" })];
    const rep = [makeEvent(0, "user.message", { content: "hi" }, "sess_rep")];
    render(
      <ReplayDiff sourceEvents={src} replayEvents={rep} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByTestId("diff-cell-sess_src-0"));
    expect(onSelect).toHaveBeenCalled();
    const [idx, row] = onSelect.mock.calls[0] ?? [];
    expect(idx).toBe(0);
    expect(row).toMatchObject({ seq: 0, changed: false });
  });

  it("shows missing placeholder when one side is shorter", () => {
    const src = [
      makeEvent(0, "user.message"),
      makeEvent(1, "assistant.message"),
    ];
    const rep = [makeEvent(0, "user.message", {}, "sess_rep")];
    render(<ReplayDiff sourceEvents={src} replayEvents={rep} />);
    // The second row's replay side is missing.
    const row1 = screen.getByTestId("diff-row-1");
    expect(row1.textContent).toContain("(missing)");
  });
});
