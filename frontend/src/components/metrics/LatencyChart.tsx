"use client";

import * as React from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { LatencyPoint } from "@/lib/api/metrics-types";
import { formatBucketTick, formatMs } from "@/lib/format-metrics";

export interface LatencyChartProps {
  data: LatencyPoint[];
  bucketSeconds: number;
  height?: number;
}

/**
 * Latency over time (p50/p95/p99) line chart. The colours match the rest
 * of the dashboard: p50 indigo, p95 amber, p99 red — bright enough to be
 * readable on both dark and light themes.
 */
export function LatencyChart({ data, bucketSeconds, height = 280 }: LatencyChartProps) {
  const ticks = React.useMemo(
    () =>
      data.map((p) => ({
        ...p,
        label: formatBucketTick(p.t, bucketSeconds),
      })),
    [data, bucketSeconds],
  );

  if (data.length === 0) {
    return (
      <div
        role="status"
        aria-label="latency chart empty"
        data-testid="latency-chart-empty"
        className="flex h-[280px] items-center justify-center text-sm text-muted-foreground"
      >
        No latency samples in this window yet.
      </div>
    );
  }

  return (
    <div data-testid="latency-chart" className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={ticks} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v: number) => formatMs(v)}
            width={70}
          />
          <RechartsTooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number, name) => [formatMs(value), name]}
            labelFormatter={(label) => `Bucket: ${label}`}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            type="monotone"
            dataKey="p50"
            name="p50"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="p95"
            name="p95"
            stroke="#f59e0b"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="p99"
            name="p99"
            stroke="#ef4444"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
