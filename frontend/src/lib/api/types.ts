/**
 * Public re-exports of API types. Consumers should import from `@/lib/api/types`
 * instead of reaching into `generated.ts` directly — that file gets rewritten
 * by codegen and the re-export layer is where we add display-only helpers.
 */
export type {
  AgentConfig,
  AgentList,
  Event,
  EventList,
  EventType,
  HealthResponse,
  ModelConfig,
  Session,
  SessionList,
  SessionListQuery,
  SessionStatus,
} from "./generated";
