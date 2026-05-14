# wake-eval-phoenix

Wake eval framework adapter for [Arize Phoenix](https://phoenix.arize.com/).

Lets you:
- Pull a Phoenix dataset and run it as a Wake eval
- Push Wake eval results back to a Phoenix experiment

## Install

```bash
pip install wake-eval-phoenix
```

## Usage

```python
from wake_eval_phoenix import PhoenixEvalAdapter

adapter = PhoenixEvalAdapter(endpoint="http://phoenix:6006")

# Pull dataset
dataset = await adapter.pull_dataset("my-dataset-name")

# Run via wake.eval runner
from wake.eval.runner import run
report = await run(dataset, invoke_fn=my_agent_invoke)

# Push results
await adapter.push_results(experiment_name="exp-2026-05-14", report=report)
```

## Status

Reference implementation. Production hardening + extended scorer plugin discovery in roadmap.
