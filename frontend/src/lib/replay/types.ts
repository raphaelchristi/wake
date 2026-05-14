/**
 * Canonical replay-side types. Mirrors `src/wake/types.py` Event +
 * `src/wake/api/routes/state.py` StateAtResponse — duplicated here on
 * purpose so the replay slice tests don't need the OpenAPI generated file
 * (which is owned by dashboard-shell and may not exist when this slice is
 * tested in isolation).
 */

export type EventType =
  | "user.message"
  | "assistant.message"
  | "assistant.thinking"
  | "assistant.delta"
  | "tool_use"
  | "tool_result"
  | "pause_turn"
  | "status"
  | "error"
  | "artifact"
  | "interrupt"
  | "provision"
  | "vault.access";

export interface WakeEvent {
  id: string;
  session_id: string;
  seq: number;
  type: EventType | string;
  payload: Record<string, unknown>;
  parent_id?: string | null;
  metadata?: Record<string, unknown> | null;
  /**
   * Tenancy: campos opcionais para back-compat com fixtures antigos.
   * Backend (>= 89bec12) sempre emite, mas tornamos opcional para que o
   * replay continue lendo logs históricos sem os campos.
   */
  organization_id?: string;
  workspace_id?: string;
  created_at: string;
}

export interface SandboxStateSnapshot {
  cwd: string;
  last_output_lines: string[];
  files_modified: string[];
}

export interface StateAtResponse {
  seq: number;
  sandbox: SandboxStateSnapshot;
  tool_calls_so_far: number;
  errors_so_far: number;
}

export type PlayState = "playing" | "paused";
export type PlaybackSpeed = 0.5 | 1 | 2 | 5;
