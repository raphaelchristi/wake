import type { Session } from "@/lib/api/types";

export const FIXTURE_SESSIONS: Session[] = [
  {
    id: "sess_01HBCD0XYZABCDEFGHJKMNPQRS",
    agent_id: "agent_01HABCDEFGHJKMNPQRSTVWXYZ",
    agent_version: 1,
    environment_id: null,
    status: "running",
    container_id: null,
    workspace_path: null,
    metadata: { model: "claude-opus-4-7" },
    organization_id: "default",
    workspace_id: "default",
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    updated_at: new Date(Date.now() - 60_000).toISOString(),
  },
  {
    id: "sess_01HBCD0YYZABCDEFGHJKMNPQRT",
    agent_id: "agent_01HBBBBBBBJKMNPQRSTVWXYZ",
    agent_version: 2,
    environment_id: "env_01HEN0000000000000000000",
    status: "terminated",
    container_id: null,
    workspace_path: null,
    metadata: { model: "claude-sonnet-4-7" },
    organization_id: "default",
    workspace_id: "default",
    created_at: new Date(Date.now() - 60 * 60_000).toISOString(),
    updated_at: new Date(Date.now() - 50 * 60_000).toISOString(),
  },
];

/**
 * Fixture alternativa pra testes multi-tenant: mesmas sessões mas num
 * outro workspace. Útil para asserções de isolamento (ex.: switch da
 * topbar deve mudar a tabela renderizada).
 */
export const FIXTURE_SESSIONS_ACME: Session[] = [
  {
    id: "sess_01HACME000000000000000001",
    agent_id: "agent_01HACME0AGENT0000000000001",
    agent_version: 1,
    environment_id: null,
    status: "running",
    container_id: null,
    workspace_path: null,
    metadata: { model: "claude-opus-4-7" },
    organization_id: "acme",
    workspace_id: "prod",
    created_at: new Date(Date.now() - 10 * 60_000).toISOString(),
    updated_at: new Date(Date.now() - 30_000).toISOString(),
  },
];
