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

import type { CostPoint } from "@/lib/api/metrics-types";
import { formatBucketTick, formatUsd } from "@/lib/format-metrics";

export interface CostChartProps {
  data: CostPoint[];
  bucketSeconds: number;
  height?: number;
}

/**
 * USD cost per bucket. Bars (not lines) because cost is a discrete sum
 * per window — line interpolation would imply something untrue.
 */
export function CostChart({ data, bucketSeconds, height = 240 }: CostChartProps) {
  const ticks = React.useMemo(
    () => data.map((p) => ({ ...p, label: formatBucketTick(p.t, bucketSeconds) })),
    [data, bucketSeconds],
  );

  if (data.length === 0) {
    return (
      <div
        role="status"
        data-testid="cost-chart-empty"
        className="flex h-[240px] items-center justify-center text-sm text-muted-foreground"
      >
        No cost samples in this window yet.
      </div>
    );
  }

  return (
    <div data-testid="cost-chart" className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={ticks} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v: number) => formatUsd(v)}
            width={70}
          />
          <RechartsTooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number) => [formatUsd(value), "cost"]}
            labelFormatter={(label) => `Bucket: ${label}`}
          />
          <Bar
            dataKey="cost_usd"
            name="USD"
            fill="#10b981"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
