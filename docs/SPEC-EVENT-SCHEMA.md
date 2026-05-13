# SPEC: Event Schema v0.1.0

> Schema canônico do event log Wake. Append-only. Compatível superficialmente com Anthropic Messages API.

Status: **Draft v0.1.0** — sujeito a revisão até v1.0.

---

## Princípios

1. **Append-only.** Eventos nunca atualizam — só novos eventos.
2. **Total ordering por sessão.** `seq` monotonicamente crescente.
3. **Compatibilidade superficial com Anthropic.** Onde possível, `content` blocks têm formato idêntico.
4. **Self-describing.** Cada evento contém tudo necessário para reprocessamento.
5. **Extensível.** Novos `type`s podem ser adicionados sem quebrar consumers existentes.

---

## Envelope comum

Todo evento tem essa estrutura:

```typescript
type Event = {
  id: string;           // ULID, globalmente único
  session_id: string;
  seq: number;          // posição na sessão (0, 1, 2, ...)
  type: EventType;
  payload: object;      // schema depende de `type`
  created_at: string;   // ISO 8601 UTC
  parent_id?: string;   // referência opcional a evento parent
  metadata?: object;    // metadata custom do cliente
};
```

JSON Schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["id", "session_id", "seq", "type", "payload", "created_at"],
  "properties": {
    "id": { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "session_id": { "type": "string" },
    "seq": { "type": "integer", "minimum": 0 },
    "type": { "type": "string" },
    "payload": { "type": "object" },
    "created_at": { "type": "string", "format": "date-time" },
    "parent_id": { "type": "string" },
    "metadata": { "type": "object" }
  }
}
```

---

## Tipos de evento

### `user.message`

User envia input ao agente.

```json
{
  "type": "user.message",
  "payload": {
    "content": [
      { "type": "text", "text": "Refactor the auth module to use hooks." }
    ]
  }
}
```

`content` segue formato de content blocks da Anthropic Messages API. Tipos suportados:

- `{ "type": "text", "text": "..." }`
- `{ "type": "image", "source": { ... } }`
- `{ "type": "container_upload", "file_id": "..." }`

---

### `assistant.message`

Resposta final do agente em um turno. Conclui um turno (`end_turn`).

```json
{
  "type": "assistant.message",
  "payload": {
    "content": [
      { "type": "text", "text": "I refactored 3 components and added 5 tests." }
    ],
    "stop_reason": "end_turn",
    "usage": {
      "input_tokens": 1542,
      "output_tokens": 387,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 1200
    }
  }
}
```

---

### `assistant.thinking`

Conteúdo de extended thinking (interno do modelo). Opcional; nem todo adapter emite.

```json
{
  "type": "assistant.thinking",
  "payload": {
    "content": "Let me first analyze the existing structure...",
    "signature": "..."
  }
}
```

---

### `assistant.delta`

Chunk parcial durante streaming. Reagregados em `assistant.message` no fim.

```json
{
  "type": "assistant.delta",
  "payload": {
    "index": 0,
    "delta": { "type": "text_delta", "text": "Let me " }
  }
}
```

**Storage:** opcional armazenar. Default: descartar após `assistant.message` final, manter só o agregado. Configurável por sessão.

---

### `tool_use`

Adapter pediu para executar uma tool. Deve preceder `tool_result` correspondente.

```json
{
  "type": "tool_use",
  "payload": {
    "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
    "name": "bash",
    "input": { "command": "ls -la" }
  }
}
```

`tool_use_id` é gerado pelo adapter, único na sessão. Usado para deduplicação e pairing com `tool_result`.

---

### `tool_result`

Resultado de uma tool. `parent_id` aponta para o `tool_use` correspondente.

```json
{
  "type": "tool_result",
  "parent_id": "01HQR2K7VXBZ9MNPL3WYCT8F00",
  "payload": {
    "tool_use_id": "toolu_01A09q90qw90lq917835lq9",
    "content": [
      { "type": "text", "text": "total 24\ndrwxr-xr-x 2 user user 4096..." }
    ],
    "is_error": false
  }
}
```

`content` segue formato de content blocks. Pode conter texto, imagens (screenshots), files.

Em erros:

```json
{
  "type": "tool_result",
  "payload": {
    "tool_use_id": "toolu_xxx",
    "content": [
      { "type": "text", "text": "Operation not permitted" }
    ],
    "is_error": true,
    "error_code": "permission_denied"
  }
}
```

`error_code` ∈ {`unavailable`, `execution_time_exceeded`, `container_expired`, `invalid_tool_input`, `too_many_requests`, `output_too_large`, `permission_denied`, `not_found`, `string_not_found`, `unknown`}.

---

### `pause_turn`

Turno pausou (long-running). Cliente pode dar continue ou interromper.

```json
{
  "type": "pause_turn",
  "payload": {
    "reason": "max_tokens",
    "can_continue": true
  }
}
```

---

### `status`

Mudança de status da sessão.

```json
{
  "type": "status",
  "payload": {
    "from": "running",
    "to": "idle",
    "reason": "end_turn"
  }
}
```

Status válidos: `idle`, `running`, `rescheduling`, `terminated`.

---

### `error`

Erro de runtime — adapter ou tool falhou de forma não-recuperável dentro do step.

```json
{
  "type": "error",
  "payload": {
    "error_type": "harness_panic",
    "message": "uncaught exception: ValueError",
    "trace": "..."
  }
}
```

Não confundir com `tool_result.is_error` (que é erro previsto de tool).

---

### `artifact`

Arquivo, blob, ou recurso gerado durante a sessão.

```json
{
  "type": "artifact",
  "payload": {
    "name": "output.png",
    "kind": "file",
    "uri": "wake://artifacts/sess_xyz/output.png",
    "mime_type": "image/png",
    "size_bytes": 18234,
    "metadata": { "generated_by": "matplotlib" }
  }
}
```

Artifacts são armazenados separado do event log (object store). O evento contém só referência.

---

### `interrupt`

Cliente pediu interrupção. Emitido pelo cliente, processado pelo runtime.

```json
{
  "type": "interrupt",
  "payload": {
    "reason": "user_requested"
  }
}
```

Runtime cancela qualquer `step()` em andamento ao detectar `interrupt`.

---

### `provision`

Sandbox provisionado.

```json
{
  "type": "provision",
  "payload": {
    "container_id": "wake_sandbox_abc123",
    "backend": "sandbox-runtime",
    "resources": { "cpu": 1, "memory_gb": 5, "disk_gb": 5 }
  }
}
```

---

### `vault.access`

Vault credential foi acessada (audit trail).

```json
{
  "type": "vault.access",
  "payload": {
    "vault_id": "github_token",
    "tool_use_id": "toolu_xxx",
    "purpose": "github.create_pr"
  }
}
```

Importante: **valor nunca é logado.** Apenas referência ao vault.

---

## Sequência típica de eventos (turn completo)

```
seq 0   user.message       "build me a CSV parser"
seq 1   status             idle → running
seq 2   provision          container provisioned
seq 3   tool_use           bash "ls"
seq 4   tool_result        "src/ tests/ README.md"
seq 5   tool_use           file_read "src/main.py"
seq 6   tool_result        "<file content>"
seq 7   tool_use           file_write "src/csv_parser.py"
seq 8   tool_result        success
seq 9   tool_use           bash "pytest tests/"
seq 10  tool_result        "5 passed"
seq 11  assistant.message  "Done. Created src/csv_parser.py with 5 tests."
seq 12  status             running → idle
```

---

## Mapeamento Anthropic Messages → eventos Wake

Para construir o array de `messages` para chamar a Messages API a partir do event log:

```python
def events_to_messages(events: list[Event]) -> list[dict]:
    messages = []
    for ev in events:
        if ev.type == "user.message":
            messages.append({"role": "user", "content": ev.payload["content"]})
        elif ev.type == "assistant.message":
            messages.append({"role": "assistant", "content": ev.payload["content"]})
        elif ev.type == "tool_use":
            # vira parte do content do último assistant message
            if messages[-1]["role"] != "assistant":
                messages.append({"role": "assistant", "content": []})
            messages[-1]["content"].append({
                "type": "tool_use",
                "id": ev.payload["tool_use_id"],
                "name": ev.payload["name"],
                "input": ev.payload["input"],
            })
        elif ev.type == "tool_result":
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": ev.payload["tool_use_id"],
                    "content": ev.payload["content"],
                    "is_error": ev.payload.get("is_error", False),
                }],
            })
    return messages
```

(Implementação real lida com `assistant.delta` agregando, `assistant.thinking`, edge cases.)

---

## Idempotência

Eventos com `tool_use_id` repetido (mesmo `id` num `tool_use` event) são deduplicados pelo runtime. Permite ao adapter re-emitir após crash sem efeito duplicado.

```sql
CREATE UNIQUE INDEX uniq_tool_use
ON events (session_id, (payload->>'tool_use_id'))
WHERE type = 'tool_use';
```

---

## Streaming via SSE

Cliente conecta:

```
GET /v1/sessions/:id/stream
Accept: text/event-stream
```

Recebe SSE no formato:

```
event: event
id: 01HQR2K7VXBZ9MNPL3WYCT8F00
data: {"type": "assistant.delta", "payload": {...}, ...}

event: event
id: 01HQR2K7VXBZ9MNPL3WYCT8F01
data: {"type": "tool_use", "payload": {...}, ...}

event: heartbeat
data: {"ts": "2026-05-13T..."}
```

`id` no SSE = `event.id` (ULID). Cliente pode reconectar com `Last-Event-ID` para resume.

---

## Storage

Backend de referência: Postgres.

Schema:

```sql
CREATE TABLE events (
  id           CHAR(26) PRIMARY KEY,
  session_id   TEXT NOT NULL,
  seq          BIGINT NOT NULL,
  type         TEXT NOT NULL,
  payload      JSONB NOT NULL,
  parent_id    CHAR(26),
  metadata     JSONB,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ON events (session_id, seq);
CREATE INDEX ON events (session_id, created_at);
CREATE INDEX ON events (parent_id) WHERE parent_id IS NOT NULL;
```

Tuning: particionamento por `session_id` hash para sessões long-tail; partition por month para sessões com >10k eventos.

Backends alternativos (plugáveis):

- SQLite (single-node local)
- Kafka + S3 (escala extrema)
- DuckDB (analytics-first)

---

## Compressão e retenção

- Eventos `assistant.delta` podem ser descartados após `assistant.message` final (configurável por sessão)
- Eventos antigos podem ser arquivados para object store frio com índice em Postgres
- Compaction da Anthropic NÃO é replicada — sessões longas com contexto demais são problema do harness, não do log

Retenção default: ilimitada. Cliente pode definir TTL por sessão.

---

## Versionamento do schema

`x-wake-schema-version` é serializado em todo evento (no metadata global da sessão):

```json
{
  "session": {
    "id": "sess_xxx",
    "schema_version": "0.1.0",
    ...
  }
}
```

Migração entre versões: documento separado, com adapters de leitura forward-compatible até v2.0.

---

## Open questions

- **Q1:** Encryption-at-rest do payload? Default off; opt-in com kms-managed key?
- **Q2:** Como representar tool_result com binário grande (megabytes)? Inline base64 ou URI?
- **Q3:** Eventos `assistant.thinking` deveriam ter flag de "redact at storage" para reduzir custo de log?
- **Q4:** `parent_id` é suficiente ou precisa de grafo completo (ex: multiagent)?

A serem resolvidos em RFC público antes de v1.0.
