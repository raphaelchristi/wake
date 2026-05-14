/**
 * Wire shapes for the Wake API. Kept in sync with `src/wake/types.py`.
 *
 * We use plain interfaces (not zod schemas) to keep the bundle tiny — the
 * Wake server is the source of truth for validation. Consumers can layer
 * their own validators on top of these types if they need stronger guards.
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

export type SessionStatus = "idle" | "running" | "rescheduling" | "terminated";

// -- Content blocks ---------------------------------------------------------

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ImageBlock {
  type: "image";
  source: Record<string, unknown>;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: TextBlock[];
  is_error?: boolean;
}

export type ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock;

// -- Configs ----------------------------------------------------------------

export interface ModelConfig {
  id: string;
  speed?: "standard" | "fast";
  provider?: string;
}

export interface ToolConfig {
  type: string;
  config?: Record<string, unknown>;
}

export interface McpServerConfig {
  name: string;
  transport: "stdio" | "http" | "sse";
  url?: string;
  command?: string;
  args?: string[];
  vault_ref?: string;
}

// -- Resources --------------------------------------------------------------

export interface AgentConfig {
  id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  model: ModelConfig;
  system?: string;
  tools: ToolConfig[];
  mcp_servers: McpServerConfig[];
  skills: Record<string, unknown>[];
  description?: string;
  metadata: Record<string, string>;
  version: number;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface Session {
  id: string;
  organization_id: string;
  workspace_id: string;
  agent_id: string;
  agent_version: number;
  environment_id?: string | null;
  status: SessionStatus;
  container_id?: string | null;
  workspace_path?: string | null;
  metadata: Record<string, string>;
  created_at: string;
  updated_at: string;
}

export interface Event {
  id: string;
  organization_id: string;
  workspace_id: string;
  session_id: string;
  seq: number;
  type: EventType;
  payload: Record<string, unknown>;
  parent_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

// -- List envelopes ---------------------------------------------------------

export interface AgentList {
  data: AgentConfig[];
}

export interface SessionList {
  data: Session[];
}

export interface EventList {
  data: Event[];
}

// -- Request bodies ---------------------------------------------------------

export interface SessionCreateRequest {
  agent_id: string;
  environment_id?: string;
  metadata?: Record<string, string>;
}

export interface AgentCreateRequest {
  name: string;
  model: ModelConfig;
  system?: string;
  tools?: ToolConfig[];
  mcp_servers?: McpServerConfig[];
  description?: string;
  metadata?: Record<string, string>;
}

export interface AgentUpdateRequest {
  name?: string;
  model?: ModelConfig;
  system?: string;
  tools?: ToolConfig[];
  mcp_servers?: McpServerConfig[];
  description?: string;
  metadata?: Record<string, string>;
}

export interface EventCreateRequest {
  type: EventType;
  payload?: Record<string, unknown>;
  parent_id?: string;
  metadata?: Record<string, unknown>;
  idempotency_key?: string;
}

export interface SessionListQuery {
  agent?: string;
  status?: SessionStatus;
  model?: string;
  since?: string | Date;
  until?: string | Date;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface StreamOptions {
  since?: number;
  lastEventId?: string;
  signal?: AbortSignal;
  /** Maximum reconnect attempts after a transport failure. Default 5. */
  maxReconnects?: number;
}
