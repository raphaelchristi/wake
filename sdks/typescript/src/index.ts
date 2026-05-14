/**
 * @wake-ai/client — Official TypeScript SDK for the Wake AI runtime.
 *
 * Works in browsers (modern + Node 18+) and emits ESM + CJS. The bundle
 * stays under 30KB gzip — zero runtime dependencies, just `fetch` and a
 * hand-rolled SSE parser.
 *
 * @example
 *
 * ```ts
 * import { WakeClient } from "@wake-ai/client";
 *
 * const wake = new WakeClient({
 *   baseUrl: "https://wake.example.com",
 *   apiKey: process.env.WAKE_API_KEY,
 *   organizationId: "org-acme",
 *   workspaceId: "ws-default",
 * });
 *
 * const agents = await wake.agents.list();
 * const session = await wake.sessions.create({ agent_id: agents[0].id });
 *
 * for await (const event of wake.sessions.stream(session.id)) {
 *   if (event.type === "assistant.delta") {
 *     process.stdout.write(String(event.payload.text ?? ""));
 *   }
 * }
 * ```
 */

export { WakeClient } from "./client.js";
export type { WakeClientOptions, RequestOptions } from "./client.js";
export { SessionsResource } from "./sessions.js";
export { AgentsResource } from "./agents.js";
export { iterSessionStream } from "./sse.js";
export {
  WakeClientError,
  WakeAPIError,
  WakeAuthError,
  WakeNotFoundError,
  WakeRateLimitError,
  WakeServerError,
  WakeTransportError,
} from "./errors.js";
export type {
  AgentConfig,
  AgentCreateRequest,
  AgentList,
  AgentUpdateRequest,
  ContentBlock,
  Event,
  EventCreateRequest,
  EventList,
  EventType,
  ImageBlock,
  McpServerConfig,
  ModelConfig,
  Session,
  SessionCreateRequest,
  SessionList,
  SessionListQuery,
  SessionStatus,
  StreamOptions,
  TextBlock,
  ToolConfig,
  ToolResultBlock,
  ToolUseBlock,
} from "./types.js";

export const VERSION = "0.1.0";
