# Edit-and-Replay

Workflow Wake pra **iteração de prompt engineering com determinismo**: pegar uma session existente, trocar `system_prompt` / `tools` / `max_steps` e re-rodar com mesmas seeds — visualizando o diff entre original e novo run.

> **Phase 8 deliverable** (Tier 2 gap #10). Backend route + frontend page side-by-side scrubber.

---

## Por que existe

Sem edit-and-replay:
- Trocar prompt → criar agent novo → criar session nova → resultado depende de RNG/temperature
- Comparar "prompt v1 vs v2" exige tooling externo (LangSmith, Phoenix)
- Loop dev é caro: cada iteração é round-trip completo

Com edit-and-replay:
- 1 click no dashboard pra "replay with diff"
- Backend reusa eventos input originais (`user.message`) + replaceia overrides
- Determinismo via seed propagation (mesmo seed → mesmo output modulo overrides)
- Visual side-by-side: original (esquerda) vs novo (direita), scrubber compartilhado

---

## API

### POST /v1/sessions/{id}/replay

Request body:
```json
{
  "system_prompt": "Override system prompt (opcional)",
  "tools": ["Override tools list (opcional)"],
  "max_steps": 10,
  "preserve_seeds": true
}
```

Response:
```json
{
  "original_session_id": "01HXXX...",
  "new_session_id": "01HYYY...",
  "diff_url": "/sessions/01HYYY.../replay?diff=01HXXX..."
}
```

Backend:
1. Lê eventos da sessão original
2. Filtra apenas eventos input (`user.message`) — descarta assistant/tool outputs
3. Cria session nova com agent (possivelmente versão diferente via canary)
4. Aplica overrides (system_prompt, tools, max_steps) no `AgentConfig` da nova session
5. Dispatcher consome eventos input + roda adapter normalmente

### Determinism guarantees

| Componente | Determinism |
|---|---|
| `seed` em `payload.metadata.seed` | ✅ propagado se `preserve_seeds=true` |
| `temperature` | ⚠️ se adapter usa, propaga seed; mas LLM temperature pode mudar mesmo com seed (provider-dependent) |
| `tool_use` IDs | ❌ ULID novos (deliberado — pra não colidir) |
| `created_at` | ❌ novo timestamp |
| `cost_usd` | ⚠️ pode variar (model pricing changes) |

**Definição operacional:** "deterministic" = mesmo `assistant.message` content (text) e mesmo `tool_use.name + tool_use.input` modulo overrides aplicados explicitamente.

---

## Frontend UX

### `/sessions/[id]/edit`

Página tem 3 seções:

1. **SessionEditor** (top) — textarea pra system prompt + multi-select tools + slider max_steps
2. **Diff toolbar** — "Run replay" button, status indicator
3. **ReplayDiff** (full-height) — side-by-side scrubber:
   - Esquerda: original session events
   - Direita: new session events (rendered as they stream in)
   - Scrubber compartilhado (mexer um move o outro até event count match)
   - Highlight em verde events new-only, vermelho events missing-from-new

### Keyboard

- ← → : prev/next event (sincroniza ambos)
- Space: toggle play/pause (replay events em sequência)
- D : diff-only mode (esconde rows iguais)

---

## Limitations

1. **Tool side-effects não rolam back** — se original session escreveu em S3, replay com mesmo tool roda de novo. Sandbox é opt-in via `dry_run=true` no replay request.
2. **External APIs random** — qualquer adapter que chama API externa (LiteLLM, GitHub) verá responses possivelmente diferentes.
3. **Cost double** — replay gasta tokens. Tracking via `agent.metadata.max_cost_usd` recomendado.
4. **Storage 2×** — events da nova session somam storage. Use `wake events archive` periódico.

---

## Integration with eval framework

Replay é a fundação do `wake eval`:

```bash
wake eval run --dataset golden.jsonl --agent agent_abc --output report.md
```

Cada row do dataset vira um replay synthético: golden input → execute via agent → score output. Mais detalhes em `docs/EVAL-FRAMEWORK.md`.

---

## Examples

### Replay com prompt nova

```python
from wake_ai_client import WakeClient

client = WakeClient(...)

# Original session
original = "01HXAY1234..."

# Replay com prompt diferente
result = await client.sessions.replay(
    original,
    system_prompt="Be more concise. Max 2 sentences.",
)

# Stream events do novo run
async for event in client.sessions.stream(result.new_session_id):
    print(event.type, event.payload)
```

### Canary com replay

```python
# Agent tem canary_weight=10 (10% de novas sessions usam v2)
# Replay particular force version explícito:
result = await client.sessions.replay(
    original_session_id,
    agent_version=2,  # override canary
)
```

---

## Testing

```bash
# Backend
pytest tests/unit/test_api_replay.py tests/unit/test_replay_engine.py -v

# Frontend
cd frontend && pnpm vitest run replay-diff
cd frontend && pnpm test:e2e --grep edit-replay
```
