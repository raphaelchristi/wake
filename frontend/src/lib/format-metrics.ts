// Slice-local format helpers. Named `format-metrics` (not just `format`)
// so it cannot collide with the canonical `lib/format.ts` the shell ships.

import { formatDistanceToNowStrict, format } from "date-fns";

export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(2)} min`;
}

export function formatUsd(value: number): string {
  if (!Number.isFinite(value)) return "$0.00";
  if (Math.abs(value) >= 1000) {
    return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }
  if (Math.abs(value) >= 1) {
    return `$${value.toFixed(2)}`;
  }
  return `$${value.toFixed(4)}`;
}

export function formatPct(rate: number): string {
  if (!Number.isFinite(rate)) return "0%";
  return `${(rate * 100).toFixed(1)}%`;
}

export function formatInt(value: number): string {
  if (!Number.isFinite(value)) return "0";
  return Math.round(value).toLocaleString("en-US");
}

export function formatFloat(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "0";
  return value.toFixed(digits);
}

export function formatBucketTick(iso: string, bucketSeconds: number): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (bucketSeconds <= 3600) return format(d, "HH:mm");
  if (bucketSeconds <= 86_400) return format(d, "HH:mm");
  if (bucketSeconds <= 86_400 * 7) return format(d, "EEE HH:mm");
  return format(d, "MMM d");
}

export function formatRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return `${formatDistanceToNowStrict(d)} ago`;
  } catch {
    return iso;
  }
}

export function formatAbsolute(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return format(d, "yyyy-MM-dd HH:mm:ss");
}
