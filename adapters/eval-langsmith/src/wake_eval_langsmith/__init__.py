"""``wake-eval-langsmith`` — LangSmith driver for the Wake eval framework.

Two-way bridge:

* **Pull**: read a LangSmith dataset (``Example`` rows) and convert it
  into :class:`wake.eval.dataset.DatasetRow` instances ready for
  :class:`wake.eval.runner.EvalRunner`.
* **Push**: take a :class:`wake.eval.runner.EvalReport` produced by the
  runner and submit it to LangSmith as a new ``Run`` per row, attached
  to the dataset's experiment timeline.

The adapter talks to LangSmith over plain HTTPS (``httpx``) so the
heavyweight upstream SDK is optional. Authentication uses the same
``LANGSMITH_API_KEY`` env var the official SDK respects.

Quick start
-----------

::

    from wake.eval import EvalRunner
    from wake_eval_langsmith import LangSmithAdapter

    adapter = LangSmithAdapter(api_key="ls-...", project="wake-prod")
    rows = adapter.pull_dataset("golden-v1")

    report = EvalRunner(invoke_fn=invoke).run_sync(rows, agent_id="agt-1")
    adapter.push_results(report, dataset_name="golden-v1")

See ``docs/EVAL-FRAMEWORK.md`` for an end-to-end recipe (CI gating,
custom scorer plugins, hybrid setups with the Phoenix driver).
"""

from wake_eval_langsmith.adapter import (
    LangSmithAdapter,
    LangSmithError,
    LangSmithExample,
)

__all__ = [
    "LangSmithAdapter",
    "LangSmithError",
    "LangSmithExample",
]

__version__ = "0.1.0"
