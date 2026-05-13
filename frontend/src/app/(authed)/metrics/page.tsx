"use client";

import * as React from "react";
import { RefreshCcw, AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CostChart } from "@/components/metrics/CostChart";
import { ErrorRateChart } from "@/components/metrics/ErrorRateChart";
import { LatencyChart } from "@/components/metrics/LatencyChart";
import { MetricsTimeRangePicker } from "@/components/metrics/MetricsTimeRangePicker";
import { ThroughputChart } from "@/components/metrics/ThroughputChart";
import { WorkerHealth } from "@/components/metrics/WorkerHealth";
import { useMetrics } from "@/hooks/useMetrics";
import { useWorkers } from "@/hooks/useWorkers";
import {
  formatFloat,
  formatInt,
  formatMs,
  formatPct,
  formatUsd,
} from "@/lib/format-metrics";
import type { MetricsWindow } from "@/lib/api/metrics-types";

const STATS_GRID =
  "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6";

export default function MetricsPage() {
  const [window, setWindow] = React.useState<MetricsWindow>("24h");
  const metrics = useMetrics({ window, autoRefreshMs: 30_000 });
  const workers = useWorkers({ autoRefreshMs: 15_000 });

  const summary = metrics.data;
  const bucketSeconds = summary?.window.bucket_seconds ?? 60;

  return (
    <div data-testid="metrics-page" className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
          <p className="text-sm text-muted-foreground">
            Live aggregates over a sliding window. Auto-refreshes every 30s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <MetricsTimeRangePicker value={window} onChange={setWindow} />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              metrics.refresh();
              workers.refresh();
            }}
            aria-label="refresh metrics"
            disabled={metrics.isFetching}
          >
            <RefreshCcw
              className={`h-4 w-4 ${metrics.isFetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            <span className="ml-2">Refresh</span>
          </Button>
        </div>
      </header>

      {metrics.error && (
        <Card data-testid="metrics-error" className="border-destructive/40">
          <CardHeader className="flex flex-row items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden="true" />
            <CardTitle className="text-destructive">
              Failed to load metrics
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{metrics.error.message}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Showing the last known good values below. Refresh to retry.
            </p>
          </CardContent>
        </Card>
      )}

      <section data-testid="metrics-summary" className={STATS_GRID}>
        <StatCard
          label="Latency p50 / p95 / p99"
          value={
            summary
              ? `${formatMs(summary.latency.p50_ms)} · ${formatMs(summary.latency.p95_ms)} · ${formatMs(summary.latency.p99_ms)}`
              : "—"
          }
          hint={summary ? `${formatInt(summary.latency.samples)} samples` : ""}
          loading={metrics.status === "loading" && !summary}
        />
        <StatCard
          label="Cost (USD)"
          value={summary ? formatUsd(summary.cost.total_usd) : "—"}
          hint={summary ? `avg ${formatUsd(summary.cost.avg_per_session_usd)} / session` : ""}
          loading={metrics.status === "loading" && !summary}
        />
        <StatCard
          label="Throughput"
          value={summary ? `${formatFloat(summary.throughput.per_hour)}/h` : "—"}
          hint={summary ? `${formatInt(summary.throughput.sessions)} sessions in window` : ""}
          loading={metrics.status === "loading" && !summary}
        />
        <StatCard
          label="Error rate"
          value={summary ? formatPct(summary.errors.rate) : "—"}
          hint={
            summary
              ? `${formatInt(summary.errors.count)} errors · ${formatInt(summary.errors.sessions_affected)} sessions affected`
              : ""
          }
          loading={metrics.status === "loading" && !summary}
          tone={summary && summary.errors.rate > 0.1 ? "warning" : "default"}
        />
        <StatCard
          label="Workers alive"
          value={summary ? formatInt(summary.workers_alive) : "—"}
          hint={summary ? `${formatInt(workers.workers.length)} reporting` : ""}
          loading={metrics.status === "loading" && !summary}
        />
        <StatCard
          label="Queue depth"
          value={summary ? formatInt(summary.queue_depth) : "—"}
          hint={summary ? "idle sessions waiting" : ""}
          loading={metrics.status === "loading" && !summary}
        />
      </section>

      <section data-testid="metrics-charts" className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Latency</CardTitle>
            <CardDescription>p50 / p95 / p99 over time</CardDescription>
          </CardHeader>
          <CardContent>
            <LatencyChart
              data={summary?.series.latency ?? []}
              bucketSeconds={bucketSeconds}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Cost</CardTitle>
            <CardDescription>USD per bucket (assistant.message + tool_result)</CardDescription>
          </CardHeader>
          <CardContent>
            <CostChart
              data={summary?.series.cost ?? []}
              bucketSeconds={bucketSeconds}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Throughput</CardTitle>
            <CardDescription>Sessions started per bucket</CardDescription>
          </CardHeader>
          <CardContent>
            <ThroughputChart
              data={summary?.series.throughput ?? []}
              bucketSeconds={bucketSeconds}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Errors</CardTitle>
            <CardDescription>Error events per bucket</CardDescription>
          </CardHeader>
          <CardContent>
            <ErrorRateChart
              data={summary?.series.errors ?? []}
              bucketSeconds={bucketSeconds}
            />
          </CardContent>
        </Card>
      </section>

      <WorkerHealth
        workers={workers.workers}
        isLoading={workers.isLoading}
        error={workers.error}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  loading,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  loading?: boolean;
  tone?: "default" | "warning";
}) {
  return (
    <Card data-testid="stat-card">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{label}</CardTitle>
          {tone === "warning" && <Badge variant="warning">attention</Badge>}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="h-7 w-24 animate-pulse rounded bg-muted/60" aria-hidden="true" />
        ) : (
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        )}
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}
