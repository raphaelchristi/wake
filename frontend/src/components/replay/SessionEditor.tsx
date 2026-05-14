/**
 * SessionEditor — system prompt + tools + max_steps override form.
 *
 * Phase 8 / Tier 2 gap #10. Plain controlled form: keeps the
 * `<textarea>` and the `<input>` controlled by local state and emits a
 * single `onReplay(overrides)` callback when the user clicks "Replay".
 *
 * The component is intentionally *display-only* with respect to the
 * source agent — it shows the original system prompt / tools as
 * placeholders so the operator knows what they are diverging from but
 * does NOT auto-fill the textarea (an empty textarea means "inherit"
 * and we want that path discoverable).
 */
"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ReplayOverrides, ReplayToolOverride } from "@/hooks/useReplay";

export interface SessionEditorProps {
  /** Read-only context shown to the operator. */
  sourceSystemPrompt?: string | null;
  sourceTools?: ReplayToolOverride[];
  sourceMaxSteps?: number | null;
  /** Disabled while a replay mutation is in flight. */
  disabled?: boolean;
  /** Submit handler — called with overrides ready for `useReplay`. */
  onReplay: (overrides: ReplayOverrides) => void;
}

function parseToolsBlob(raw: string): ReplayToolOverride[] | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  // Accept either a JSON array OR newline-separated names.
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed
        .map((item) => {
          if (typeof item === "string") return { name: item };
          if (item && typeof item === "object" && "name" in item) {
            const obj = item as Record<string, unknown>;
            return {
              name: String(obj.name ?? ""),
              description:
                typeof obj.description === "string" ? obj.description : undefined,
            };
          }
          return null;
        })
        .filter((t): t is ReplayToolOverride => Boolean(t && t.name));
    }
  } catch {
    /* fall through to newline parsing */
  }
  return trimmed
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((name) => ({ name }));
}

export function SessionEditor({
  sourceSystemPrompt,
  sourceTools,
  sourceMaxSteps,
  disabled = false,
  onReplay,
}: SessionEditorProps): React.ReactElement {
  const [systemPrompt, setSystemPrompt] = React.useState("");
  const [toolsText, setToolsText] = React.useState("");
  const [maxStepsText, setMaxStepsText] = React.useState("");
  const [seedText, setSeedText] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const sourceToolsLabel = React.useMemo(() => {
    if (!sourceTools || sourceTools.length === 0) return "none";
    return sourceTools.map((t) => t.name).join(", ");
  }, [sourceTools]);

  const handleSubmit = React.useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      setError(null);
      const overrides: ReplayOverrides = {};

      const sp = systemPrompt.trim();
      if (sp.length > 0) overrides.system_prompt = sp;

      const tools = parseToolsBlob(toolsText);
      if (tools !== undefined) overrides.tools = tools;

      if (maxStepsText.trim().length > 0) {
        const n = Number.parseInt(maxStepsText.trim(), 10);
        if (!Number.isFinite(n) || n < 1 || n > 1000) {
          setError("max_steps must be an integer in [1, 1000]");
          return;
        }
        overrides.max_steps = n;
      }

      if (seedText.trim().length > 0) {
        const n = Number.parseInt(seedText.trim(), 10);
        if (!Number.isFinite(n) || n < 0) {
          setError("seed must be a non-negative integer");
          return;
        }
        overrides.seed = n;
      }

      onReplay(overrides);
    },
    [systemPrompt, toolsText, maxStepsText, seedText, onReplay],
  );

  return (
    <form
      data-testid="session-editor"
      onSubmit={handleSubmit}
      className="flex h-full flex-col gap-4 p-4"
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="system-prompt">System prompt override</Label>
        <textarea
          id="system-prompt"
          data-testid="system-prompt-input"
          rows={10}
          disabled={disabled}
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder={
            sourceSystemPrompt
              ? `Inherit: ${sourceSystemPrompt.slice(0, 120)}${
                  sourceSystemPrompt.length > 120 ? "…" : ""
                }`
              : "Leave blank to inherit the source agent's system prompt"
          }
          className="rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
        <p className="text-xs text-slate-500">
          Blank = inherit. Any value REPLACES the original system prompt.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="tools-override">Tools override</Label>
        <textarea
          id="tools-override"
          data-testid="tools-input"
          rows={4}
          disabled={disabled}
          value={toolsText}
          onChange={(e) => setToolsText(e.target.value)}
          placeholder={`Inherit: ${sourceToolsLabel}\n(one tool name per line, or JSON array)`}
          className="rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
        <p className="text-xs text-slate-500">
          Blank = inherit. Any value REPLACES the visible tool list.
        </p>
      </div>

      <div className="flex flex-row gap-3">
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="max-steps">max_steps</Label>
          <Input
            id="max-steps"
            data-testid="max-steps-input"
            disabled={disabled}
            value={maxStepsText}
            onChange={(e) => setMaxStepsText(e.target.value)}
            placeholder={
              sourceMaxSteps != null ? `Inherit: ${sourceMaxSteps}` : "Inherit"
            }
            inputMode="numeric"
          />
        </div>
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="seed">seed</Label>
          <Input
            id="seed"
            data-testid="seed-input"
            disabled={disabled}
            value={seedText}
            onChange={(e) => setSeedText(e.target.value)}
            placeholder="Inherit from source"
            inputMode="numeric"
          />
        </div>
      </div>

      {error ? (
        <div
          data-testid="editor-error"
          role="alert"
          className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300"
        >
          {error}
        </div>
      ) : null}

      <div className="flex items-center justify-end gap-2 pt-2">
        <Button
          type="submit"
          data-testid="replay-submit"
          disabled={disabled}
        >
          {disabled ? "Replaying…" : "Replay"}
        </Button>
      </div>
    </form>
  );
}
