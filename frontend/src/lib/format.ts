import { formatDistanceToNowStrict, intervalToDuration } from "date-fns";

/** Truncate a ULID for display: first 8 chars + ellipsis. */
export function shortId(id: string): string {
  if (id.length <= 12) return id;
  // Strip a known prefix like `sess_` first
  const underscore = id.indexOf("_");
  const body = underscore >= 0 && underscore < 6 ? id.slice(underscore + 1) : id;
  return `${body.slice(0, 8)}…`;
}

/** Render an ISO date as a relative string ("3 minutes ago"). */
export function relativeTime(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return formatDistanceToNowStrict(d, { addSuffix: true });
}

/** Render a duration in seconds as a compact human-readable string. */
export function durationLabel(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  if (seconds < 1) return "<1s";
  const dur = intervalToDuration({ start: 0, end: Math.round(seconds) * 1000 });
  const parts: string[] = [];
  if (dur.hours) parts.push(`${dur.hours}h`);
  if (dur.minutes) parts.push(`${dur.minutes}m`);
  if (dur.seconds || parts.length === 0) parts.push(`${dur.seconds ?? 0}s`);
  return parts.join(" ");
}

/** Render USD value with two decimals. */
export function usd(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value);
}
