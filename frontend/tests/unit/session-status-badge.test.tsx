import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionStatusBadge } from "@/components/sessions/SessionStatusBadge";

describe("SessionStatusBadge", () => {
  it.each([
    ["idle", "Idle"],
    ["running", "Running"],
    ["rescheduling", "Rescheduling"],
    ["terminated", "Terminated"],
  ] as const)("renders %s as '%s'", (status, label) => {
    render(<SessionStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
