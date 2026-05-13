/**
 * Replay helpers — colors, summaries, time math.
 *
 * Kept framework-free so unit tests can exercise the logic without spinning
 * up React / TanStack Query.
 */

import type { EventType, WakeEvent } from "./types";

/**
 * Tailwind background-color tokens per event type. The scrubber, event list,
 * and badge all consume this map so the palette stays consistent.
 */
export const EVENT_TYPE_BG: Record<string, string> = {
  "user.message": "bg-blue-500",
  "assistant.message": "bg-green-500",
  "assistant.delta": "bg-green-500",
  "assistant.thinking": "bg-emerald-400",
  tool_use: "bg-purple-500",
  tool_result: "bg-amber-500",
  pause_turn: "bg-yellow-400",
  status: "bg-slate-400",
  error: "bg-red-500",
  artifact: "bg-fuchsia-500",
  interrupt: "bg-red-400",
  provision: "bg-slate-500",
  "vault.access": "bg-orange-500",
};

export const EVENT_TYPE_FG: Record<string, string> = {
  "user.message": "text-blue-700 dark:text-blue-300",
  "assistant.message": "text-green-700 dark:text-green-300",
  "assistant.delta": "text-green-700 dark:text-green-300",
  "assistant.thinking": "text-emerald-700 dark:text-emerald-300",
  tool_use: "text-purple-700 dark:text-purple-300",
  tool_result: "text-amber-700 dark:text-amber-300",
  status: "text-slate-600 dark:text-slate-400",
  error: "text-red-700 dark:text-red-300",
  "vault.access": "text-orange-700 dark:text-orange-300",
  provision: "text-slate-600 dark:text-slate-400",
};

export function colorForEventType(type: EventType | string): string {
  // sandbox.* and vault.* prefixes collapse to a single color.
  if (type.startsWith("sandbox.")) return "bg-slate-500";
  if (type.startsWith("vault.")) return "bg-orange-500";
  if (type.startsWith("error")) return "bg-red-500";
  return EVENT_TYPE_BG[type] ?? "bg-gray-400";
}

export function textColorForEventType(type: EventType | string): string {
  if (type.startsWith("sandbox.")) return "text-slate-600 dark:text-slate-400";
  if (type.startsWith("vault.")) return "text-orange-700 dark:text-orange-300";
  return EVENT_TYPE_FG[type] ?? "text-gray-600 dark:text-gray-400";
}

/**
 * Single-line human label for an event in the event list. Falls back to the
 * raw type when payload doesn't have a friendly summary.
 */
export function summarizeEvent(ev: WakeEvent): string {
  const p = ev.payload ?? {};
  switch (ev.type) {
    case "user.message":
    case "assistant.message": {
      const content = (p as { content?: unknown }).content;
      if (Array.isArray(content)) {
        const text = content.find(
          (b): b is { type: string; text: string } =>
            typeof b === "object" && b !== null && (b as { type?: string }).type === "text",
        );
        if (text && typeof text.text === "string") {
          return text.text.slice(0, 120);
        }
      }
      return "(message)";
    }
    case "tool_use": {
      const name = (p as { name?: string }).name ?? "tool";
      const input = (p as { input?: Record<string, unknown> }).input ?? {};
      if (name === "bash" && typeof input.command === "string") {
        return `bash: ${input.command.slice(0, 100)}`;
      }
      const path = input.path ?? input.file_path;
      if (typeof path === "string") return `${name}: ${path}`;
      return `${name}`;
    }
    case "tool_result": {
      const content = (p as { content?: unknown }).content;
      if (Array.isArray(content)) {
        const text = content.find(
          (b): b is { type: string; text: string } =>
            typeof b === "object" && b !== null && (b as { type?: string }).type === "text",
        );
        if (text && typeof text.text === "string") {
          const isError = (p as { is_error?: boolean }).is_error;
          const prefix = isError ? "[err] " : "";
          return prefix + text.text.split("\n")[0]?.slice(0, 100);
        }
      }
      return "(result)";
    }
    case "status": {
      const from = (p as { from?: string }).from;
      const to = (p as { to?: string }).to;
      return `${from ?? "?"} → ${to ?? "?"}`;
    }
    case "error": {
      return ((p as { message?: string }).message ?? "error").slice(0, 120);
    }
    case "vault.access": {
      return `vault: ${(p as { vault_id?: string }).vault_id ?? "?"}`;
    }
    default:
      return ev.type;
  }
}

/**
 * Compute tick positions (0..1) for a sorted-by-seq event list.
 *
 * We use linear seq-based positioning rather than timestamp-based: a session
 * with bursty events would otherwise have illegible clusters on the
 * timeline.
 */
export function tickPositions(events: WakeEvent[]): number[] {
  if (events.length === 0) return [];
  if (events.length === 1) return [0.5];
  const denom = events.length - 1;
  return events.map((_, i) => i / denom);
}

/**
 * Given a click x in [0, width], find the closest event index.
 */
export function indexFromX(x: number, width: number, count: number): number {
  if (count <= 0) return 0;
  if (width <= 0) return 0;
  const clamped = Math.max(0, Math.min(width, x));
  const ratio = clamped / width;
  return Math.round(ratio * (count - 1));
}

/**
 * Clamp an integer into [min, max]. Pure-function for testability.
 */
export function clampIndex(value: number, count: number): number {
  if (count <= 0) return 0;
  return Math.max(0, Math.min(count - 1, Math.trunc(value)));
}

export * from "./types";
