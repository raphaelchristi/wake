"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, MoonStar } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Worker, WorkerStatus } from "@/lib/api/metrics-types";
import { formatRelative } from "@/lib/format-metrics";

export interface WorkerHealthProps {
  workers: Worker[];
  isLoading?: boolean;
  error?: Error | null;
}

const STATUS_LABEL: Record<WorkerStatus, string> = {
  alive: "alive",
  stale: "stale",
  idle: "idle",
};

const STATUS_VARIANT: Record<
  WorkerStatus,
  "success" | "warning" | "secondary"
> = {
  alive: "success",
  stale: "warning",
  idle: "secondary",
};

const STATUS_ICON: Record<WorkerStatus, React.ReactNode> = {
  alive: <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />,
  stale: <AlertTriangle className="h-4 w-4 text-amber-500" aria-hidden="true" />,
  idle: <MoonStar className="h-4 w-4 text-muted-foreground" aria-hidden="true" />,
};

export function WorkerHealth({ workers, isLoading, error }: WorkerHealthProps) {
  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Workers</CardTitle>
          <CardDescription>Failed to load worker list.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error.message}</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading && workers.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Workers</CardTitle>
          <CardDescription>Heartbeats updated every ~15s.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="h-20 animate-pulse rounded-md bg-muted/50"
                aria-hidden="true"
              />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (workers.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Workers</CardTitle>
          <CardDescription>Heartbeats updated every ~15s.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No workers reporting. If you’re running SQLite single-process this
            is normal until a session starts.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workers</CardTitle>
        <CardDescription>
          {workers.length} reporting · alive ={" "}
          {workers.filter((w) => w.status === "alive").length}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul
          data-testid="worker-grid"
          className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-4"
        >
          {workers.map((w) => (
            <li
              key={w.worker_id}
              data-testid="worker-card"
              data-status={w.status}
              className={cn(
                "rounded-md border border-border bg-card p-3",
                w.status === "stale" && "border-amber-500/40",
                w.status === "alive" && "border-emerald-500/40",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 truncate">
                  {STATUS_ICON[w.status]}
                  <span className="truncate font-mono text-xs" title={w.worker_id}>
                    {w.worker_id}
                  </span>
                </div>
                <Badge variant={STATUS_VARIANT[w.status]}>
                  {STATUS_LABEL[w.status]}
                </Badge>
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted-foreground">
                <dt>Heartbeat</dt>
                <dd className="text-right">{formatRelative(w.last_heartbeat_at)}</dd>
                <dt>Sessions</dt>
                <dd className="text-right">{w.current_sessions.length}</dd>
              </dl>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
