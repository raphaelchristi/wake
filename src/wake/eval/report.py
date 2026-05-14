"""Render :class:`EvalReport` instances to markdown / JSON.

Two outputs:

* **Markdown** — for humans + Github comment posting. Has a summary
  table, per-row table, and any errors. Sticks to GitHub-flavoured
  markdown so it renders nicely in PR comments.
* **JSON** — for machines + downstream consumers (LangSmith / Phoenix
  push). Keeps the full structure including events.

Both writers accept either a path or a file-like object so tests can
capture them in-memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import IO, Any

from wake.eval.runner import EvalReport, RowReport


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def to_markdown(report: EvalReport, *, max_detail_chars: int = 240) -> str:
    """Render the report as a markdown document.

    ``max_detail_chars`` trims long scorer details (e.g. when comparing
    a 2-kilobyte expected blob) so the table stays usable. Full details
    survive in the JSON output.
    """
    lines: list[str] = []
    lines.append(f"# Eval Report — agent `{report.agent_id}`")
    lines.append("")
    lines.append(f"- Dataset: `{report.dataset_path}`")
    lines.append(f"- Started: {_fmt_ts(report.started_at)}")
    lines.append(f"- Finished: {_fmt_ts(report.finished_at)}")
    lines.append(f"- Duration: {report.duration_s:.2f}s")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total rows | {report.total} |")
    lines.append(f"| Passed | {report.passed} |")
    lines.append(f"| Failed | {report.failed} |")
    lines.append(f"| Errored | {report.errored} |")
    lines.append(f"| Accuracy | {_fmt_pct(report.accuracy)} |")
    lines.append(f"| Mean score | {report.mean_score:.3f} |")
    if report.latency_mean_ms is not None:
        lines.append(f"| Latency mean | {report.latency_mean_ms:.1f} ms |")
    if report.latency_p95_ms is not None:
        lines.append(f"| Latency p95 | {report.latency_p95_ms:.1f} ms |")
    if report.total_cost_usd > 0:
        lines.append(f"| Total cost | ${report.total_cost_usd:.4f} |")
    lines.append("")
    lines.append("## Rows")
    lines.append("")
    lines.append("| ID | Status | Scores | Latency (ms) | Cost (USD) | Details |")
    lines.append("|---|---|---|---|---|---|")
    for row in report.rows:
        status = _row_status(row)
        scores = ", ".join(
            f"{s.name}={s.score:.2f}{'✓' if s.passed else '✗'}" for s in row.scores
        ) or "—"
        latency = (
            f"{row.invocation.latency_ms:.1f}"
            if row.invocation is not None and row.invocation.latency_ms is not None
            else "—"
        )
        cost = (
            f"{row.invocation.cost_usd:.4f}"
            if row.invocation is not None and row.invocation.cost_usd is not None
            else "—"
        )
        details = _row_detail(row, max_chars=max_detail_chars)
        lines.append(
            f"| `{row.row_id}` | {status} | {scores} | {latency} | {cost} | {details} |"
        )
    errored_rows = [r for r in report.rows if r.error is not None]
    if errored_rows:
        lines.append("")
        lines.append("## Errors")
        lines.append("")
        for row in errored_rows:
            lines.append(f"- `{row.row_id}`: {row.error}")
    return "\n".join(lines) + "\n"


def _row_status(row: RowReport) -> str:
    if row.error is not None:
        return "error"
    return "pass" if row.passed else "fail"


def _row_detail(row: RowReport, *, max_chars: int) -> str:
    if row.error is not None:
        return _escape(_clip(row.error, max_chars))
    if not row.scores:
        return "no scorers ran"
    snippets = [s.details for s in row.scores if s.details]
    if not snippets:
        return "—"
    return _escape(_clip(" · ".join(snippets), max_chars))


def _clip(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


def _escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ↵ ")


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_ts(ts: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(timespec="seconds")


def write_markdown(report: EvalReport, dest: str | Path | IO[str]) -> None:
    text = to_markdown(report)
    if hasattr(dest, "write"):
        dest.write(text)  # type: ignore[union-attr]
        return
    Path(dest).write_text(text, encoding="utf-8")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(report: EvalReport) -> dict[str, Any]:
    """Serialise the report to a JSON-friendly dict.

    Dataclass conversion happens via ``asdict``; we then prune the raw
    DatasetRow (which is large and redundant) down to its key fields.
    """
    payload: dict[str, Any] = {
        "agent_id": report.agent_id,
        "dataset_path": report.dataset_path,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_s": report.duration_s,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "errored": report.errored,
            "accuracy": report.accuracy,
            "mean_score": report.mean_score,
            "latency_mean_ms": report.latency_mean_ms,
            "latency_p95_ms": report.latency_p95_ms,
            "total_cost_usd": report.total_cost_usd,
        },
        "rows": [_row_to_json(r) for r in report.rows],
        "metadata": dict(report.metadata),
    }
    return payload


def _row_to_json(row: RowReport) -> dict[str, Any]:
    return {
        "row_id": row.row_id,
        "passed": row.passed,
        "error": row.error,
        "input": row.row.input,
        "expected": row.row.expected,
        "metadata": dict(row.row.metadata),
        "aggregate_score": row.aggregate_score,
        "scores": [asdict(s) for s in row.scores],
        "invocation": _invocation_to_json(row),
    }


def _invocation_to_json(row: RowReport) -> dict[str, Any] | None:
    if row.invocation is None:
        return None
    return {
        "output": row.invocation.output,
        "latency_ms": row.invocation.latency_ms,
        "cost_usd": row.invocation.cost_usd,
        "session_id": row.invocation.session_id,
        "events": list(row.invocation.events),
        "metadata": dict(row.invocation.metadata),
    }


def write_json(report: EvalReport, dest: str | Path | IO[str], *, indent: int = 2) -> None:
    payload = to_json(report)
    if hasattr(dest, "write"):
        json.dump(payload, dest, indent=indent, default=str)  # type: ignore[arg-type]
        return
    Path(dest).write_text(  # type: ignore[arg-type]
        json.dumps(payload, indent=indent, default=str) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "to_json",
    "to_markdown",
    "write_json",
    "write_markdown",
]
