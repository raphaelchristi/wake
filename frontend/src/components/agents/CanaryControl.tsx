/**
 * CanaryControl — slider + apply button to set `metadata.canary_weight`.
 *
 * Phase 8 / Tier 2 gap #12. The slider is a plain HTML `<input
 * type="range">` (no external dependency) wired to the
 * `useApplyCanary` mutation. Promotion semantics:
 *   - 0  → clear `canary_weight` (full rollback to stable)
 *   - 100 → all new sessions hit the canary (promote)
 *   - 1..99 → weighted split — the backend `select_version` rolls
 *             `random.uniform(0, 100)` per new session.
 *
 * Display intentionally surfaces the **latest** weight on the *latest*
 * version: there is only one canary at a time by contract.
 */
"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export interface CanaryControlProps {
  /** Current weight on the latest version (0 = stable). */
  currentWeight: number;
  /** Latest version number — informational only. */
  latestVersion: number;
  /** True while the PATCH mutation is pending. */
  pending?: boolean;
  /** Called with weight 0-100 OR `null` to remove the key. */
  onApply: (weight: number | null) => void;
}

export function CanaryControl({
  currentWeight,
  latestVersion,
  pending = false,
  onApply,
}: CanaryControlProps): React.ReactElement {
  const [draft, setDraft] = React.useState<number>(currentWeight);

  // Keep the slider in sync if the parent receives a fresh value
  // (e.g. after a successful mutation invalidates the cache).
  React.useEffect(() => {
    setDraft(currentWeight);
  }, [currentWeight]);

  const dirty = draft !== currentWeight;
  const status =
    currentWeight === 0
      ? "stable"
      : currentWeight === 100
        ? "promoted"
        : "canary";

  return (
    <div
      data-testid="canary-control"
      className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium">Canary rollout</h3>
          <Badge
            data-testid="canary-status-badge"
            variant={
              status === "stable"
                ? "muted"
                : status === "promoted"
                  ? "success"
                  : "warning"
            }
          >
            {status}
          </Badge>
        </div>
        <span className="text-xs text-slate-500">
          latest: v{latestVersion}
        </span>
      </div>

      <div className="flex items-center gap-3">
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={draft}
          disabled={pending}
          onChange={(e) => setDraft(Number.parseInt(e.target.value, 10))}
          data-testid="canary-slider"
          aria-label="Canary weight"
          className="flex-1 accent-blue-600"
        />
        <span
          data-testid="canary-weight-display"
          className="w-12 text-right font-mono text-sm tabular-nums"
        >
          {draft}%
        </span>
      </div>

      <p className="text-xs text-slate-500">
        {draft === 0
          ? "All new sessions use the latest stable version."
          : draft === 100
            ? "All new sessions hit the canary — equivalent to promoting it to stable."
            : `~${draft}% of new sessions route to the canary; ~${100 - draft}% stay on stable.`}
      </p>

      <div className="flex items-center justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          data-testid="canary-clear"
          disabled={pending || currentWeight === 0}
          onClick={() => {
            setDraft(0);
            onApply(null);
          }}
        >
          Clear canary
        </Button>
        <Button
          type="button"
          data-testid="canary-apply"
          disabled={pending || !dirty}
          onClick={() => onApply(draft)}
        >
          {pending ? "Applying…" : "Apply"}
        </Button>
      </div>
    </div>
  );
}
