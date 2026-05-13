import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LatencyChart } from "@/components/metrics/LatencyChart";
import { CostChart } from "@/components/metrics/CostChart";
import { ThroughputChart } from "@/components/metrics/ThroughputChart";
import { ErrorRateChart } from "@/components/metrics/ErrorRateChart";
import { WorkerHealth } from "@/components/metrics/WorkerHealth";
import {
  formatMs,
  formatUsd,
  formatPct,
  formatBucketTick,
} from "@/lib/format-metrics";

describe("metrics formatters", () => {
  it("formats ms / s / min", () => {
    expect(formatMs(0)).toBe("—");
    expect(formatMs(450)).toBe("450 ms");
    expect(formatMs(1500)).toBe("1.50 s");
    expect(formatMs(75_000)).toBe("1.25 min");
  });

  it("formats USD with appropriate precision", () => {
    expect(formatUsd(0)).toBe("$0.0000");
    expect(formatUsd(0.0034)).toBe("$0.0034");
    expect(formatUsd(1.5)).toBe("$1.50");
    expect(formatUsd(1234)).toBe("$1,234");
  });

  it("formats percentage", () => {
    expect(formatPct(0)).toBe("0.0%");
    expect(formatPct(0.123)).toBe("12.3%");
  });

  it("formats bucket ticks", () => {
    const iso = "2025-01-01T12:34:00Z";
    expect(formatBucketTick(iso, 60)).toMatch(/^\d{2}:\d{2}$/);
    expect(formatBucketTick(iso, 86_400)).toMatch(/^\d{2}:\d{2}$/);
    expect(formatBucketTick(iso, 86_400 * 7)).toMatch(/\d{2}:\d{2}/);
  });
});

describe("LatencyChart", () => {
  it("renders the empty state when data is empty", () => {
    render(<LatencyChart data={[]} bucketSeconds={60} />);
    expect(screen.getByTestId("latency-chart-empty")).toBeInTheDocument();
  });

  it("renders the chart container when data is present", () => {
    const data = [
      { t: "2025-01-01T00:00:00Z", p50: 100, p95: 200, p99: 300 },
      { t: "2025-01-01T00:01:00Z", p50: 120, p95: 250, p99: 320 },
    ];
    render(<LatencyChart data={data} bucketSeconds={60} />);
    expect(screen.getByTestId("latency-chart")).toBeInTheDocument();
  });
});

describe("CostChart", () => {
  it("shows empty state", () => {
    render(<CostChart data={[]} bucketSeconds={60} />);
    expect(screen.getByTestId("cost-chart-empty")).toBeInTheDocument();
  });

  it("renders bars when populated", () => {
    render(
      <CostChart
        data={[{ t: "2025-01-01T00:00:00Z", cost_usd: 0.42 }]}
        bucketSeconds={60}
      />,
    );
    expect(screen.getByTestId("cost-chart")).toBeInTheDocument();
  });
});

describe("ThroughputChart", () => {
  it("shows empty state", () => {
    render(<ThroughputChart data={[]} bucketSeconds={60} />);
    expect(screen.getByTestId("throughput-chart-empty")).toBeInTheDocument();
  });

  it("renders chart container", () => {
    render(
      <ThroughputChart
        data={[{ t: "2025-01-01T00:00:00Z", sessions: 5 }]}
        bucketSeconds={60}
      />,
    );
    expect(screen.getByTestId("throughput-chart")).toBeInTheDocument();
  });
});

describe("ErrorRateChart", () => {
  it("shows empty state", () => {
    render(<ErrorRateChart data={[]} bucketSeconds={60} />);
    expect(screen.getByTestId("error-chart-empty")).toBeInTheDocument();
  });

  it("renders chart container", () => {
    render(
      <ErrorRateChart
        data={[{ t: "2025-01-01T00:00:00Z", errors: 3 }]}
        bucketSeconds={60}
      />,
    );
    expect(screen.getByTestId("error-chart")).toBeInTheDocument();
  });
});

describe("WorkerHealth", () => {
  it("renders empty state when no workers", () => {
    render(<WorkerHealth workers={[]} />);
    expect(
      screen.getByText(/No workers reporting/i),
    ).toBeInTheDocument();
  });

  it("renders worker cards with status badges", () => {
    render(
      <WorkerHealth
        workers={[
          {
            worker_id: "w-1",
            status: "alive",
            last_heartbeat_at: new Date().toISOString(),
            current_session_id: "s-abc",
            current_sessions: ["s-abc"],
          },
          {
            worker_id: "w-2",
            status: "stale",
            last_heartbeat_at: new Date(Date.now() - 60_000).toISOString(),
            current_session_id: null,
            current_sessions: [],
          },
          {
            worker_id: "w-3",
            status: "idle",
            last_heartbeat_at: null,
            current_session_id: null,
            current_sessions: [],
          },
        ]}
      />,
    );
    const cards = screen.getAllByTestId("worker-card");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveAttribute("data-status", "alive");
    expect(cards[1]).toHaveAttribute("data-status", "stale");
    expect(cards[2]).toHaveAttribute("data-status", "idle");
  });

  it("renders error state when error provided", () => {
    render(<WorkerHealth workers={[]} error={new Error("boom")} />);
    expect(screen.getByText(/Failed to load worker list/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});
