"""Wake eval framework — ``wake eval`` CLI + library API.

The eval framework runs a JSONL dataset of ``(input, expected)`` pairs
through a target Wake agent (via the API server) and produces a scored
report. It is intentionally split into four small modules:

* :mod:`wake.eval.dataset` — JSONL reader + row schema
* :mod:`wake.eval.scorer`  — built-in scorers + plugin discovery
* :mod:`wake.eval.runner`  — async runner that calls an ``invoke_fn``
  per row and aggregates results
* :mod:`wake.eval.report`  — markdown + JSON writers

External adapter packages (``wake-eval-langsmith``, ``wake-eval-phoenix``)
import this module to convert their native dataset shapes and push
results back to their own systems. See ``docs/EVAL-FRAMEWORK.md`` for
end-to-end recipes.
"""

from __future__ import annotations

from wake.eval.dataset import (
    DatasetError,
    DatasetRow,
    load_jsonl,
    parse_row,
    read_jsonl,
    rows_from_objects,
)
from wake.eval.report import (
    to_json,
    to_markdown,
    write_json,
    write_markdown,
)
from wake.eval.runner import (
    AgentInvocation,
    EvalReport,
    EvalRunner,
    RowReport,
)
from wake.eval.scorer import (
    ExactMatchScorer,
    LLMJudgeScorer,
    RegexScorer,
    Scorer,
    ScorerRegistry,
    ScorerResult,
    default_registry,
)

__all__ = [
    # dataset
    "DatasetError",
    "DatasetRow",
    "load_jsonl",
    "parse_row",
    "read_jsonl",
    "rows_from_objects",
    # scorer
    "ExactMatchScorer",
    "LLMJudgeScorer",
    "RegexScorer",
    "Scorer",
    "ScorerRegistry",
    "ScorerResult",
    "default_registry",
    # runner
    "AgentInvocation",
    "EvalReport",
    "EvalRunner",
    "RowReport",
    # report
    "to_json",
    "to_markdown",
    "write_json",
    "write_markdown",
]
