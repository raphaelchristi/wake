/**
 * useReplay — POST /v1/sessions/{id}/replay.
 *
 * Phase 8 / Tier 2 gap #10. The hook wraps the replay endpoint in a
 * TanStack `useMutation` so the SessionEditor page can drive it with
 * loading / error states without re-implementing fetch boilerplate.
 *
 * Surface intentionally narrow:
 *   - `replay(overrides)` triggers `POST /v1/sessions/{sourceId}/replay`
 *     with `{system_prompt?, tools?, max_steps?, seed?}` body.
 *   - On success, the result payload (`ReplayResult` shape from
 *     `src/wake/types.py`) lands on `mutation.data` for the page to
 *     stash and pass into `<ReplayDiff>` for the side-by-side render.
 *
 * The replay endpoint is **synchronous**: it materialises the new
 * session, copies events under the new id and returns. The hook does
 * not poll — callers should treat the returned `new_session_id` as
 * immediately fetchable via `useEvents(new_session_id)`.
 */
"use client";

import { useMutation, type UseMutationResult } from "@tanstack/react-query";
import { request } from "@/lib/api/client";

export interface ReplayToolOverride {
  name: string;
  description?: string;
  input_schema?: Record<string, unknown>;
}

export interface ReplayOverrides {
  system_prompt?: string;
  tools?: ReplayToolOverride[];
  max_steps?: number;
  seed?: number;
}

export interface ReplayResult {
  source_session_id: string;
  new_session_id: string;
  seed: number;
  deterministic: boolean;
  overrides_applied: string[];
  source_event_count: number;
  replayed_event_count: number;
}

/**
 * Drive a single replay against `sourceSessionId`. Returns a mutation
 * handle so the UI can show pending / error / success states. The
 * `mutateAsync` form is exposed (via `mutation.mutateAsync`) for the
 * page to await before navigation.
 */
export function useReplay(
  sourceSessionId: string | undefined,
): UseMutationResult<ReplayResult, Error, ReplayOverrides> {
  return useMutation<ReplayResult, Error, ReplayOverrides>({
    mutationKey: ["replay", sourceSessionId],
    mutationFn: async (overrides: ReplayOverrides) => {
      if (!sourceSessionId) {
        throw new Error("useReplay: missing sourceSessionId");
      }
      return request<ReplayResult>("POST", `/v1/sessions/${sourceSessionId}/replay`, {
        body: overrides,
      });
    },
  });
}
