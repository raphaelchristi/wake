"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { MetricsWindow } from "@/lib/api/metrics-types";

const OPTIONS: { value: MetricsWindow; label: string }[] = [
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

export interface MetricsTimeRangePickerProps {
  value: MetricsWindow;
  onChange: (value: MetricsWindow) => void;
  className?: string;
}

export function MetricsTimeRangePicker({
  value,
  onChange,
  className,
}: MetricsTimeRangePickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="metrics time range"
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 p-1",
        className,
      )}
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <Button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            variant={active ? "default" : "ghost"}
            size="sm"
            onClick={() => onChange(opt.value)}
            className={cn(
              "min-w-[3rem] text-xs",
              !active && "text-muted-foreground",
            )}
          >
            {opt.label}
          </Button>
        );
      })}
    </div>
  );
}
