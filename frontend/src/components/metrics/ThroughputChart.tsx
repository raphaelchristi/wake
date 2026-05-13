"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ThroughputPoint } from "@/lib/api/metrics-types";
import { formatBucketTick, formatInt } from "@/lib/format-metrics";

export interface ThroughputChartProps {
  data: ThroughputPoint[];
  bucketSeconds: number;
  height?: number;
}

/**
 * Sessions/h area chart. Area fill gives the operator a quick visual
 * sense of total volume; XAxis labels are formatted by bucket size.
 */
export function ThroughputChart({ data, bucketSeconds, height = 240 }: ThroughputChartProps) {
  const ticks = React.useMemo(
    () => data.map((p) => ({ ...p, label: formatBucketTick(p.t, bucketSeconds) })),
    [data, bucketSeconds],
  );

  if (data.length === 0) {
    return (
      <div
        role="status"
        data-testid="throughput-chart-empty"
        className="flex h-[240px] items-center justify-center text-sm text-muted-foreground"
      >
        No sessions started in this window yet.
      </div>
    );
  }

  return (
    <div data-testid="throughput-chart" className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={ticks} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
          <defs>
            <linearGradient id="wake-throughput-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickFormatter={(v: number) => formatInt(v)}
            width={50}
            allowDecimals={false}
          />
          <RechartsTooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value: number) => [formatInt(value), "sessions"]}
            labelFormatter={(label) => `Bucket: ${label}`}
          />
          <Area
            type="monotone"
            dataKey="sessions"
            stroke="#3b82f6"
            strokeWidth={2}
            fill="url(#wake-throughput-fill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
