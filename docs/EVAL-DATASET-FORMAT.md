# Wake Eval Dataset Format

Datasets pra `wake eval run` são JSONL — uma linha JSON por row. Schema simples + compat com LangSmith e Phoenix formats via adapters.

---

## Schema

Cada linha:

```typescript
type DatasetRow = {
  input: Record<string, any>;       // Required. What we send to the agent.
  expected?: Record<string, any>;   // Optional. What we expect back. Scorers use this.
  metadata?: Record<string, any>;   // Optional. Free-form tags (category, source, etc.).
};
```

### `input`

Dict que vira `user.message.payload`. Para agentes texto-em-texto:

```jsonl
{"input": {"text": "What is the capital of France?"}}
```

Para agentes que aceitam structured input:

```jsonl
{"input": {"text": "Analyze this", "context": {"url": "https://...", "headers": {}}}}
```

Wake eval runner usa `input` AS-IS como `payload` no event `user.message`. Adapter (sua impl) interpreta.

### `expected`

Dict que scorers consomem. Schema depende do scorer:

| Scorer | Expected shape |
|---|---|
| `exact_match` | `{"text": "<exact response>"}` |
| `regex` | `{"pattern": "<regex>"}` |
| `contains` | `{"substring": "<string>"}` |
| `json_match` | dict — keys must appear in output JSON com mesmos valores |
| `llm_judge` | `{"rubric": "Output should be concise and factual"}` |

Custom scorers definem seu próprio schema.

### `metadata`

Free-form. Comum:

```jsonl
{"input": {...}, "expected": {...}, "metadata": {"category": "math", "difficulty": "easy", "source": "GSM8K"}}
```

Report agrupa por metadata keys quando `--group-by <key>` flag passada.

---

## Examples

### Factual Q&A com exact_match

```jsonl
{"input": {"text": "Capital of France?"}, "expected": {"text": "Paris"}}
{"input": {"text": "Capital of Japan?"}, "expected": {"text": "Tokyo"}}
{"input": {"text": "Capital of Brazil?"}, "expected": {"text": "Brasília"}}
```

```bash
wake eval run --dataset capitals.jsonl --agent agent_abc --scorer exact_match
```

### Math com regex

```jsonl
{"input": {"text": "2 + 2"}, "expected": {"pattern": "^4$|^four$"}, "metadata": {"category": "math"}}
{"input": {"text": "5 × 6"}, "expected": {"pattern": "^30$|^thirty$"}, "metadata": {"category": "math"}}
```

```bash
wake eval run --dataset math.jsonl --agent agent_abc --scorer regex
```

### Structured output com json_match

```jsonl
{"input": {"text": "Extract name from: 'Alice is 30'"}, "expected": {"name": "Alice"}}
{"input": {"text": "Extract name from: 'Bob is 25'"}, "expected": {"name": "Bob"}}
```

```bash
wake eval run --dataset extract.jsonl --agent agent_abc --scorer json_match
```

### Open-ended com llm_judge

```jsonl
{"input": {"text": "Write a haiku about autumn"}, "expected": {"rubric": "5-7-5 syllable count, autumn imagery, evocative tone"}}
```

```bash
wake eval run --dataset haiku.jsonl --agent agent_abc --scorer llm_judge
```

LLM judge config via env:
```bash
WAKE_EVAL_JUDGE_MODEL=claude-opus-4-7
WAKE_EVAL_JUDGE_API_KEY=$WAKE_API_KEY
```

---

## LangSmith dataset compat

LangSmith datasets têm shape:
```json
{
  "inputs": {"question": "..."},
  "outputs": {"answer": "..."},
  "metadata": {"tags": ["..."]}
}
```

`wake-eval-langsmith` adapter converte automaticamente:
- `inputs` → `input`
- `outputs` → `expected`
- `metadata` → `metadata`

```python
from wake_eval_langsmith import LangSmithEvalAdapter
adapter = LangSmithEvalAdapter(api_key="...")
rows = await adapter.pull_dataset("my-ls-dataset")
# rows são wake.eval format já
```

---

## Phoenix dataset compat

Phoenix usa shape similar:
```json
{
  "input": {...},
  "output": {...},
  "metadata": {...}
}
```

`wake-eval-phoenix` adapter mapeia `output` → `expected` automaticamente.

---

## Best practices

### 1. Small datasets first

Comece com 10-50 rows. Detecta bugs no scorer / adapter cedo.

### 2. Diversidade de categories

Use `metadata.category` pra balancear:
- Happy path (60%)
- Edge cases (25%)
- Adversarial (15%)

Report mostra breakdown por category.

### 3. Versionamento

Commit datasets em git. Quando dataset muda:
- `golden-v1.jsonl` (immutable, baseline)
- `golden-v2.jsonl` (current)

Tag eval runs com `--metadata dataset_version=v2`.

### 4. Não vazar credenciais

Datasets em git público NÃO devem ter API keys, PII, secret prompts. Use placeholders:

```jsonl
{"input": {"text": "Search docs at $API_URL"}, "expected": {...}}
```

Runner substitui `$API_URL` por env var antes de submit.

### 5. Rubrics claras pro llm_judge

Vague rubrics → vague judgment:
- ❌ `{"rubric": "Should be good"}`
- ✅ `{"rubric": "Output must mention at least 2 of: tariffs, exchange rates, GDP. No more than 200 words."}`

---

## Schema validation

`wake eval run` valida cada linha antes de submeter:
- `input` é dict não-vazio? — required
- JSON parseável? — required
- `expected.<scorer-specific-key>` presente? — required (per scorer)

Linhas inválidas são pulled out e listadas no report como "skipped" com motivo.

---

## Schema future-proofing

Reserved keys que podem ganhar semantic no future:
- `input.seed` — controla RNG (Phase 9+ replay determinism)
- `expected.tolerances` — fuzzy match thresholds
- `metadata.timeout_ms` — per-row timeout override
- `metadata.expected_cost_usd` — budget check
- `metadata.tags` — labels for filtering

Atual: estes ainda não são interpretados pelo runner — vivem em metadata até implementação.

---

## Conversion utilities

Convert from CSV:
```python
import csv, json
with open("input.csv") as f, open("output.jsonl", "w") as out:
    for row in csv.DictReader(f):
        out.write(json.dumps({
            "input": {"text": row["question"]},
            "expected": {"text": row["answer"]},
            "metadata": {"row_id": row.get("id")},
        }) + "\n")
```

Convert from HuggingFace dataset:
```python
from datasets import load_dataset
ds = load_dataset("gsm8k", "main", split="test[:100]")
with open("gsm8k.jsonl", "w") as f:
    for row in ds:
        f.write(json.dumps({
            "input": {"text": row["question"]},
            "expected": {"pattern": f"#### {row['answer'].split('####')[1].strip()}"},
            "metadata": {"category": "math"},
        }) + "\n")
```
