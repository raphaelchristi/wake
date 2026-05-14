# wake-eval-langsmith

> LangSmith driver for the Wake eval framework. Pull datasets, run them through a Wake agent, push results back as runs + feedback.

The `wake-eval-langsmith` package bridges [LangSmith](https://smith.langchain.com) datasets and the in-process [`wake eval`](https://github.com/raphaelchristi/wake/tree/main/docs/EVAL-FRAMEWORK.md) runner. Use it when your team already curates eval datasets in LangSmith and you want Wake agents scored against the same source of truth.

## Install

```bash
pip install wake-eval-langsmith
```

For development inside the Wake monorepo:

```bash
pip install -e adapters/eval-langsmith
```

The package depends on `wake-ai` (the core runtime) and `httpx`. The official `langsmith` SDK is **optional** — we speak the REST API directly so air-gapped self-hosted installs work without bundling extra wheels.

## Quick start

```python
from wake.eval import EvalRunner
from wake_eval_langsmith import LangSmithAdapter

adapter = LangSmithAdapter(
    api_key="ls-...",          # or set LANGSMITH_API_KEY
    project="wake-prod",       # optional
)

rows = adapter.pull_dataset("golden-v1")

def invoke(row):
    # Your wake agent invocation here.
    ...

report = EvalRunner(invoke_fn=invoke, scorers="exact_match").run_sync(
    rows, agent_id="agt-123"
)

result = adapter.push_results(report, dataset_name="golden-v1")
print(f"pushed {result['created_runs']} runs, {result['created_feedback']} feedback rows")
```

## Authentication

| Source | Variable / argument |
|---|---|
| Constructor | `LangSmithAdapter(api_key="ls-...")` |
| Environment | `LANGSMITH_API_KEY` |
| Endpoint override | `LANGSMITH_ENDPOINT` (default `https://api.smith.langchain.com`) |
| Project | `LANGSMITH_PROJECT` or `project=` |

Pass `endpoint="https://langsmith.internal/your-org"` (or set `LANGSMITH_ENDPOINT`) to point at a self-hosted LangSmith instance.

## API surface

| Method | Behaviour |
|---|---|
| `get_dataset(name)` | GET `/datasets?name=<name>`, returns the raw dataset dict |
| `list_examples(dataset_id, limit=1000)` | Pages `/examples?dataset=<id>` until exhausted (or `limit`) |
| `pull_dataset(name, limit=1000)` | Convenience: resolve dataset by name → return `list[DatasetRow]` |
| `push_results(report, dataset_name, experiment_prefix)` | Creates one Run per row + one Feedback per scorer |

### Determinism

`push_results` derives a deterministic UUIDv5 from `(agent_id, row_id)` for every run. Re-pushing the same suite **updates** instead of duplicating, which lets you wire `wake eval` into CI without polluting your LangSmith timeline.

### Row mapping

LangSmith examples store `inputs` and `outputs` as opaque dicts. We collapse 1-key dicts into the value (so `{"text": "hi"}` becomes `"hi"`); multi-key dicts pass through unchanged. The example ID lands in `metadata.id` so each Wake row keeps the LangSmith identity.

## CI recipe

```yaml
# .github/workflows/eval.yml
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install wake-ai wake-eval-langsmith
      - env:
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        run: |
          python -m my_team.eval --dataset golden-v1 --fail-under 0.85
```

The runner's `--fail-under` flag (or programmatic `report.accuracy < threshold`) gates the build.

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

All tests use `httpx.MockTransport` — no real LangSmith calls.

## License

Apache-2.0 (matches the Wake monorepo).
