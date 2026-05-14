/**
 * Agents resource: create / list / get / update / archive / versions.
 */

import type { WakeClient } from "./client.js";
import type {
  AgentConfig,
  AgentCreateRequest,
  AgentList,
  AgentUpdateRequest,
} from "./types.js";

export class AgentsResource {
  constructor(private readonly client: WakeClient) {}

  async create(params: AgentCreateRequest, options: { signal?: AbortSignal } = {}): Promise<AgentConfig> {
    return this.client.request<AgentConfig>("POST", "/v1/agents", {
      body: params,
      signal: options.signal,
    });
  }

  async list(options: { signal?: AbortSignal } = {}): Promise<AgentConfig[]> {
    const res = await this.client.request<AgentList>("GET", "/v1/agents", {
      signal: options.signal,
    });
    return res?.data ?? [];
  }

  async get(
    agentId: string,
    options: { version?: number; signal?: AbortSignal } = {}
  ): Promise<AgentConfig> {
    return this.client.request<AgentConfig>(
      "GET",
      `/v1/agents/${encodeURIComponent(agentId)}`,
      {
        query: options.version !== undefined ? { version: options.version } : undefined,
        signal: options.signal,
      }
    );
  }

  async update(
    agentId: string,
    body: AgentUpdateRequest,
    options: { signal?: AbortSignal } = {}
  ): Promise<AgentConfig> {
    return this.client.request<AgentConfig>(
      "PATCH",
      `/v1/agents/${encodeURIComponent(agentId)}`,
      { body, signal: options.signal }
    );
  }

  async archive(agentId: string, options: { signal?: AbortSignal } = {}): Promise<AgentConfig> {
    return this.client.request<AgentConfig>(
      "POST",
      `/v1/agents/${encodeURIComponent(agentId)}/archive`,
      { signal: options.signal }
    );
  }

  async listVersions(agentId: string, options: { signal?: AbortSignal } = {}): Promise<AgentConfig[]> {
    const res = await this.client.request<AgentList>(
      "GET",
      `/v1/agents/${encodeURIComponent(agentId)}/versions`,
      { signal: options.signal }
    );
    return res?.data ?? [];
  }
}
