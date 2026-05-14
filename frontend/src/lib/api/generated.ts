/**
 * Generated type stubs.
 *
 * This file is normally produced by `pnpm openapi:generate` against the Wake
 * FastAPI `openapi.json`. We commit a hand-curated minimal shape so the
 * project type-checks and builds without requiring a live backend in CI.
 *
 * After backend changes, run `pnpm openapi:generate` to refresh this file.
 *
 * DO NOT EDIT BY HAND once regeneration is wired up — the generator will
 * overwrite the entire file. We only ship a hand-written stub for the shell
 * slice while the codegen pipeline is being established.
 */

export type SessionStatus = "idle" | "running" | "rescheduling" | "terminated";

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

export interface Session {
  id: string;
  agent_id: string;
  agent_version: number;
  environment_id: string | null;
  status: SessionStatus;
  container_id: string | null;
  workspace_path: string | null;
  metadata: Record<string, string>;
  /** Tenancy: organização dona da sessão (default: `default`). */
  organization_id: string;
  /** Tenancy: workspace dentro da organização (default: `default`). */
  workspace_id: string;
  created_at: string;
  updated_at: string;
}

export interface SessionList {
  data: Session[];
}

export interface ModelConfig {
  id: string;
  speed?: "standard" | "fast";
  provider?: string;
}

export interface AgentConfig {
  id: string;
  name: string;
  model: ModelConfig;
  system?: string | null;
  description?: string | null;
  metadata: Record<string, string>;
  version: number;
  /** Tenancy: organização dona da config (default: `default`). */
  organization_id: string;
  /** Tenancy: workspace dentro da organização (default: `default`). */
  workspace_id: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface AgentList {
  data: AgentConfig[];
}

export interface Event {
  id: string;
  session_id: string;
  seq: number;
  type: EventType;
  payload: Record<string, unknown>;
  parent_id: string | null;
  metadata: Record<string, unknown> | null;
  /** Tenancy: organização à qual o evento pertence. */
  organization_id: string;
  /** Tenancy: workspace ao qual o evento pertence. */
  workspace_id: string;
  created_at: string;
}

export interface EventList {
  data: Event[];
}

export interface HealthResponse {
  status: string;
  version: string;
  components: Record<string, unknown>;
}

/** Query params accepted by GET /v1/sessions (Phase 5 dashboard-shell). */
export interface SessionListQuery {
  agent?: string;
  status?: SessionStatus;
  model?: string;
  since?: string;
  until?: string;
  q?: string;
  page?: number;
  page_size?: number;
}
