"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ErrorPoint } from "@/lib/api/metrics-types";
import { formatBucketTick, formatInt } from "@/lib/format-metrics";

export interface ErrorRateChartProps {
  data: ErrorPoint[];
  bucketSeconds: number;
  height?: number;
}

/**
 * Errors emitted per bucket. Red bars so it visually pops next to the
 * green cost chart and blue throughput chart.
 */
export function ErrorRateChart({ data, bucketSeconds, height = 200 }: ErrorRateChartProps) {
  const ticks = React.useMemo(
    () => data.map((p) => ({ ...p, label: formatBucketTick(p.t, bucketSeconds) })),
    [data, bucketSeconds],
  );

  if (data.length === 0) {
    return (
      <div
        role="status"
        data-testid="error-chart-empty"
        className="flex h-[200px] items-center justify-center text-sm text-muted-foreground"
      >
        No errors observed in this window — quiet skies.
      </div>
    );
  }

  return (
    <div data-testid="error-chart" className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={ticks} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v: number) => formatInt(v)}
            width={40}
            allowDecimals={false}
          />
          <RechartsTooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number) => [formatInt(value), "errors"]}
            labelFormatter={(label) => `Bucket: ${label}`}
          />
          <Bar
            dataKey="errors"
            name="errors"
            fill="#ef4444"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
