# Agent Versioning + Canary Deploy

Wake versiona AgentConfig automaticamente (cada `update` que muda content hash cria versão nova). Phase 8 adiciona UI dashboard pra diff entre versões + canary weighted rollout.

> Tier 2 gap #12. Backend já fazia versioning desde Phase 1; faltava UX.

---

## Versioning model

Cada `Agent` tem N versões (1-indexed). Mudanças via:

```python
await client.agents.update(agent_id, system="new prompt")
# → versão N+1 created se content hash difere
```

Content hash:
- `name + model + system + tools + mcp_servers + skills + description + metadata` (canonical JSON)
- Mudança em qualquer = nova versão
- Mudança em `metadata` que afeta canary_weight = nova versão (sim, intencional — operações de canary são auditáveis)

### List versions

```python
versions = await client.agents.versions(agent_id)
for v in versions.data:
    print(v.version, v.created_at, v.content_hash[:8])
```

### Get specific version

```python
agent_v3 = await client.agents.get(agent_id, version=3)
```

---

## Dashboard UI

### `/agents/[id]/versions`

Mostra timeline horizontal:

```
  v1 (init) ─── v2 (system) ─── v3 (tools) ─── v4 (canary 5%) ─── v5 (canary 25%)
                                                  ▲ latest
```

Click numa versão = side panel com:
- `system` diff vs versão adjacent (line-by-line)
- `tools` diff (added/removed)
- `metadata` diff
- Audit: created_at, who_changed (futura phase com user identity)

### Canary control

`AgentControl` component:

```
┌─ Canary deploy v5 ──────────────────────────┐
│                                              │
│  Weight: [────●────────] 25%                 │
│           0%          100%                   │
│                                              │
│  [Apply]  [Set 0% (rollback)]               │
│                                              │
│  Last 24h:                                   │
│  - 120 new sessions used v5 (25.2%)         │
│  - 356 new sessions used v4 (74.8%)         │
└──────────────────────────────────────────────┘
```

---

## Canary mechanics

Server-side weighted random. `agent.metadata.canary_weight` (0-100, integer percent) controla:

```python
def select_version(agent_id: str, weight: int) -> int:
    if random.random() * 100 < weight:
        return latest_version
    return previous_stable_version
```

Stable version = `agent.metadata.stable_version` (default: max version - 1 quando weight > 0).

### Promotion

```python
# Promote v5 → 100% (kills canary)
await client.agents.update(
    agent_id,
    metadata={"canary_weight": "100", "stable_version": "5"},
)
```

### Rollback

```python
# Kill canary, all traffic to stable
await client.agents.update(
    agent_id,
    metadata={"canary_weight": "0"},
)
```

### Force version

Per-session override:

```python
session = await client.sessions.create(
    agent_id="agent_abc",
    agent_version=3,  # explicit, ignores canary
)
```

---

## Diff format

`AgentVersionDiff` component renderiza:

- **Removed lines** (red, `-` prefix)
- **Added lines** (green, `+` prefix)
- **Context** (white, 3 lines around changes)
- **Word-level intra-line diff** pra prompts longos (usa `diff-match-patch`)

Tools/MCP/Skills diff = list-based:
- Items added: green `+ tool_name`
- Items removed: red `- tool_name`
- Items modified: yellow `~ tool_name` + sub-diff do config

---

## Audit log

Cada `agents.update()` emite `event` na session-less store:

```json
{
  "type": "agent.version.created",
  "agent_id": "agent_abc",
  "from_version": 4,
  "to_version": 5,
  "content_hash": "sha256:...",
  "changes": {"system": true, "metadata.canary_weight": "5 → 25"},
  "created_at": "2026-05-14T...",
  "workspace_id": "prod"
}
```

(Phase 9+ adicionará `user_id` quando RBAC integration estiver completa.)

---

## Testing

```bash
pytest tests/unit/test_canary.py -v
cd frontend && pnpm vitest run canary-control
```

---

## Limitations

- Canary weight é integer 0-100 (sem float — evita drift de granular weights)
- Stable version não pode ser > current version
- Sem A/B/n testing (só A vs B canary). Multi-version A/B fica pra Phase 11+ se houver demand.
- Rollback é tudo-ou-nada (sem gradual rollback). Workaround: set weight=0 e re-canary com weight=N pra ramp gradual.
