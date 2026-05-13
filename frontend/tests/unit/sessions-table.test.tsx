import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/link / next/navigation are mocked because we render the component in
// isolation (no Next.js router in jsdom).
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={typeof href === "string" ? href : "#"} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/sessions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { SessionsTable } from "@/components/sessions/SessionsTable";

import { FIXTURE_SESSIONS } from "../fixtures/sessions";

describe("SessionsTable", () => {
  it("renders the column headers", () => {
    render(<SessionsTable sessions={[]} emptyMessage="Nothing yet." />);
    for (const header of ["Session", "Agent", "Status", "Model", "Created", "Duration", "Events"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
  });

  it("renders an empty state when there are no sessions", () => {
    render(<SessionsTable sessions={[]} emptyMessage="No sessions yet." />);
    expect(screen.getByText("No sessions yet.")).toBeInTheDocument();
  });

  it("renders a row per session with model + status visible", () => {
    render(<SessionsTable sessions={FIXTURE_SESSIONS} />);
    for (const s of FIXTURE_SESSIONS) {
      expect(screen.getByTestId(`session-row-${s.id}`)).toBeInTheDocument();
    }
    expect(screen.getByText("claude-opus-4-7")).toBeInTheDocument();
    expect(screen.getAllByText(/Running|Terminated/).length).toBeGreaterThan(0);
  });

  it("renders a loading state when isLoading and no sessions", () => {
    render(<SessionsTable sessions={[]} isLoading />);
    expect(screen.getByText(/Loading sessions/i)).toBeInTheDocument();
  });
});
