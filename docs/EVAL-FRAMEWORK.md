# Wake Eval Framework

`wake eval` runs a JSONL dataset of `(input, expected)` pairs through a Wake agent and produces a scored report. Backbone do "golden workflow" de prompt engineering: dataset → agent → metrics (cost, accuracy, latency).

> **Phase 8 deliverable** (Tier 2 gap #11). Adapters: LangSmith + Phoenix (separate packages).

---

## Quickstart

### 1. Prepare dataset (JSONL)

`golden.jsonl`:
```jsonl
{"input": {"text": "summarize the moon landing"}, "expected": {"text": "Apollo 11..."}, "metadata": {"category": "history"}}
{"input": {"text": "what is 2+2?"}, "expected": {"text": "4"}, "metadata": {"category": "math"}}
{"input": {"text": "translate hello to french"}, "expected": {"text": "bonjour"}, "metadata": {"category": "translation"}}
```

Schema: cada linha JSON com `input` (dict), `expected` (dict opcional), `metadata` (dict opcional). Ver `docs/EVAL-DATASET-FORMAT.md`.

### 2. Run

```bash
wake eval run \
  --dataset golden.jsonl \
  --agent agent_abc \
  --scorer exact_match \
  --output report.md
```

Output `report.md`:
```markdown
# Wake Eval Report — agent_abc

| metric | value |
|---|---|
| total_rows | 3 |
| passed | 2 (66.7%) |
| failed | 1 (33.3%) |
| avg_cost_usd | 0.0042 |
| avg_latency_p95_ms | 1832 |

## Failures

### Row 2 (category: math)
- Expected: `{"text": "4"}`
- Got: `{"text": "The answer is 4."}`
- Scorer (`exact_match`): FAIL
```

---

## Built-in scorers

| Scorer | What | Use case |
|---|---|---|
| `exact_match` | output text == expected text (case-sensitive) | factual Q&A |
| `regex` | regex from expected.pattern matches output text | format validation |
| `llm_judge` | LLM grades output against expected (1-5 scale) | open-ended / creative |
| `contains` | expected substring in output | partial-match |
| `json_match` | output parses to JSON + key-by-key match with expected | structured outputs |

### Custom scorer (plugin)

Define em pacote separado, register via entry_points:

```python
# my_pkg/scorers.py
from wake.eval.scorer import Scorer, ScoreResult

class MyCustomScorer:
    name = "my_custom"

    def score(self, output: dict, expected: dict, metadata: dict) -> ScoreResult:
        # ...
        return ScoreResult(pass_=True, score=0.85, detail="weighted match")
```

`pyproject.toml`:
```toml
[project.entry-points."wake.eval.scorers"]
my_custom = "my_pkg.scorers:MyCustomScorer"
```

Install, then:
```bash
wake eval run ... --scorer my_custom
```

---

## CLI

### `wake eval run`

```bash
wake eval run \
  --dataset PATH       # JSONL dataset path
  --agent ID           # Wake agent ID
  --scorer NAME        # built-in or plugin (default: exact_match)
  --output PATH        # markdown report (default: stdout)
  --json PATH          # JSON detailed report
  --workspace ID       # tenant scope (default: $WAKE_WORKSPACE_ID)
  --concurrency N      # parallel rows (default: 5)
  --max-rows N         # cap rows (default: all)
  --base-url URL       # Wake API (default: $WAKE_API_URL)
  --api-key KEY        # auth (default: $WAKE_API_KEY)
```

### `wake eval list`

Lista evals já rodadas (lê metadata em sessions com `metadata.eval_run_id`).

### `wake eval show <run-id>`

Print report de uma eval run salva.

---

## Adapter pattern (LangSmith / Phoenix)

Adapters externos (`wake-eval-langsmith`, `wake-eval-phoenix`) implementam:
- `pull_dataset(name) → list[Row]` — converte dataset native pro shape wake.eval
- `push_results(experiment_name, results)` — empurra report de volta

### LangSmith

```bash
pip install wake-eval-langsmith
```

```python
from wake_eval_langsmith import LangSmithEvalAdapter
from wake.eval.runner import run

adapter = LangSmithEvalAdapter(api_key="...", endpoint="https://api.smith.langchain.com")

# Pull dataset from LangSmith
dataset = await adapter.pull_dataset("my-langsmith-dataset")

# Run via Wake agent
report = await run(dataset, agent_id="agent_abc", scorer="exact_match")

# Push back to LangSmith
await adapter.push_results("wake-2026-05-14", report)
```

### Phoenix

```bash
pip install wake-eval-phoenix
```

```python
from wake_eval_phoenix import PhoenixEvalAdapter
adapter = PhoenixEvalAdapter(endpoint="http://phoenix:6006")
dataset = await adapter.pull_dataset("my-phoenix-ds")
# ... run ...
await adapter.push_results("exp-2026", report)
```

Both adapters discovered via entry_points namespace `wake.eval.adapters`. Add your own:

```toml
[project.entry-points."wake.eval.adapters"]
mlflow = "my_pkg.mlflow_adapter:MLFlowEvalAdapter"
```

---

## Programmatic API

```python
from wake.eval.dataset import load_jsonl
from wake.eval.runner import run
from wake.eval.report import to_markdown

dataset = load_jsonl("golden.jsonl")
report = await run(
    dataset,
    agent_id="agent_abc",
    scorer="exact_match",
    base_url="http://wake:8080",
    api_key="...",
    workspace_id="prod",
)

print(to_markdown(report))
```

Each row execution = 1 Wake session created → user.message appended → wait for terminated → score output.

---

## Concurrency model

`--concurrency 5` runs 5 rows in parallel. Each row = independent session. Rate-limit applies (Phase 7 — 60/min writes default), so high concurrency may hit 429 — runner retries with exponential backoff (honors `Retry-After`).

Recommended ranges:
- Dev / smoke: `--concurrency 1`
- Production eval: `--concurrency 5-10`
- Stress test eval: `--concurrency 20+` (verify rate-limit configured)

---

## CI integration

Eval em CI workflow:

```yaml
# .github/workflows/eval.yml
name: Daily eval
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install wake-ai-client wake-ai
      - run: |
          wake eval run \
            --dataset golden.jsonl \
            --agent ${{ secrets.WAKE_AGENT_ID }} \
            --output report.md \
            --json report.json
        env:
          WAKE_API_URL: ${{ secrets.WAKE_API_URL }}
          WAKE_API_KEY: ${{ secrets.WAKE_API_KEY }}
      - uses: actions/upload-artifact@v4
        with:
          name: eval-report
          path: report.*
      - name: Fail if regression
        run: |
          pass_rate=$(jq '.passed / .total_rows' report.json)
          python -c "exit(0 if $pass_rate >= 0.85 else 1)"
```

---

## Cost tracking

Cada session faz LLM calls — custo somado por `metadata.cost_usd` em events. Report agrega `avg_cost_usd` + `p95_cost_usd`. Combine com Phase 7 cost-budget pra hard cap:

```bash
# Cria agent só pra eval com budget
wake agents create \
  --name eval-agent \
  --metadata max_cost_usd=5.00
```

---

## Replay determinism

Eval rolls fresh session por row. Determinism via:
- `preserve_seeds=true` (replay engine — Phase 8 dx-edit-replay)
- Fixed `seed` em metadata se adapter suportar

⚠️ LLM `temperature` pode produzir output ligeiramente diferente run-to-run. `llm_judge` scorer é robusto a isso; `exact_match` pode flake — use `regex` ou `contains` quando appropriate.

---

## Limitations

- Eval roda contra Wake **rodando** (não offline). Você precisa server up.
- Concurrency limitada por rate-limit (Phase 7) — 60/min writes default.
- Sem golden trace replay nesse phase (Phase 9+).
- Sem A/B comparison entre 2 agents na mesma run (workaround: rodar duas vezes + diff reports).

---

## Roadmap

- Phase 9: trace recording + golden replay (compare exact event sequence)
- Phase 9: A/B comparison built-in (`wake eval run --agent A --vs B`)
- Phase 11+: integration com memory primitives + multi-agent eval
