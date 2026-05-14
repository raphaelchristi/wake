/**
 * Component tests for CanaryControl.
 *
 * Locks in:
 *  - status badge mirrors currentWeight (stable / canary / promoted)
 *  - slider input updates the displayed weight
 *  - apply button is disabled when draft equals currentWeight
 *  - clear button calls onApply(null)
 *  - pending prop disables interactive controls
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CanaryControl } from "@/components/agents/CanaryControl";

describe("<CanaryControl />", () => {
  it("renders stable badge when weight is 0", () => {
    render(
      <CanaryControl
        currentWeight={0}
        latestVersion={3}
        onApply={() => undefined}
      />,
    );
    expect(screen.getByTestId("canary-status-badge").textContent).toBe(
      "stable",
    );
    expect(screen.getByTestId("canary-weight-display").textContent).toBe(
      "0%",
    );
  });

  it("renders canary badge when weight is in (0, 100)", () => {
    render(
      <CanaryControl
        currentWeight={25}
        latestVersion={4}
        onApply={() => undefined}
      />,
    );
    expect(screen.getByTestId("canary-status-badge").textContent).toBe(
      "canary",
    );
    expect(screen.getByTestId("canary-weight-display").textContent).toBe(
      "25%",
    );
  });

  it("renders promoted badge when weight is 100", () => {
    render(
      <CanaryControl
        currentWeight={100}
        latestVersion={5}
        onApply={() => undefined}
      />,
    );
    expect(screen.getByTestId("canary-status-badge").textContent).toBe(
      "promoted",
    );
  });

  it("apply button is disabled until the slider value differs", () => {
    render(
      <CanaryControl
        currentWeight={20}
        latestVersion={2}
        onApply={() => undefined}
      />,
    );
    const apply = screen.getByTestId("canary-apply") as HTMLButtonElement;
    expect(apply.disabled).toBe(true);

    const slider = screen.getByTestId("canary-slider") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "55" } });
    expect(screen.getByTestId("canary-weight-display").textContent).toBe("55%");
    expect(apply.disabled).toBe(false);
  });

  it("clicking apply calls onApply with the draft weight", () => {
    const onApply = vi.fn();
    render(
      <CanaryControl currentWeight={0} latestVersion={1} onApply={onApply} />,
    );
    const slider = screen.getByTestId("canary-slider") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "40" } });
    fireEvent.click(screen.getByTestId("canary-apply"));
    expect(onApply).toHaveBeenCalledWith(40);
  });

  it("clear button calls onApply(null) and is disabled when already stable", () => {
    const onApply = vi.fn();
    const { rerender } = render(
      <CanaryControl currentWeight={0} latestVersion={1} onApply={onApply} />,
    );
    const clear = screen.getByTestId("canary-clear") as HTMLButtonElement;
    expect(clear.disabled).toBe(true);

    rerender(
      <CanaryControl currentWeight={30} latestVersion={1} onApply={onApply} />,
    );
    const clear2 = screen.getByTestId("canary-clear") as HTMLButtonElement;
    expect(clear2.disabled).toBe(false);
    fireEvent.click(clear2);
    expect(onApply).toHaveBeenCalledWith(null);
  });

  it("disables apply + slider while pending", () => {
    render(
      <CanaryControl
        currentWeight={0}
        latestVersion={1}
        pending
        onApply={() => undefined}
      />,
    );
    expect((screen.getByTestId("canary-apply") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByTestId("canary-slider") as HTMLInputElement).disabled).toBe(
      true,
    );
    expect((screen.getByTestId("canary-clear") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getByTestId("canary-apply").textContent).toContain("Applying");
  });

  it("syncs draft when currentWeight prop changes (e.g. after refetch)", () => {
    const { rerender } = render(
      <CanaryControl
        currentWeight={10}
        latestVersion={1}
        onApply={() => undefined}
      />,
    );
    expect(screen.getByTestId("canary-weight-display").textContent).toBe("10%");
    rerender(
      <CanaryControl
        currentWeight={70}
        latestVersion={1}
        onApply={() => undefined}
      />,
    );
    expect(screen.getByTestId("canary-weight-display").textContent).toBe("70%");
  });
});
