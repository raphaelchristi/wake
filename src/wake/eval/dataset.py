"""Eval dataset reader.

Datasets are stored as JSONL (one JSON object per line) so they
diff nicely under git and can be streamed with no peak-memory cost.

Schema
------

Each line is::

    {
        "input": <string | object>,
        "expected": <string | object | null>,
        "metadata": {
            "id": <string>,        # optional, defaults to the 1-indexed row number
            "tags": [<string>],    # optional
            "scorer": <string>,    # optional per-row scorer override
            "scorer_args": <obj>,  # optional kwargs forwarded to the scorer
            ...                    # arbitrary key/values preserved verbatim
        }
    }

``input`` may be a plain string (treated as ``user.message`` text) or
an object with at minimum a ``text`` key — adapters may also accept a
full ``messages`` array. ``expected`` is opaque to the runner; it is
forwarded to the chosen scorer.

The reader is intentionally permissive:

* blank lines and lines starting with ``#`` are skipped, so authors can
  inline comments without breaking JSONL semantics
* a line is allowed to omit ``expected`` (the runner falls back to
  ``None``, and only scorers that require a target — e.g. ``exact_match``
  — will fail at row time, not at parse time)
* an explicit ``input`` is REQUIRED; a row without it raises
  :class:`DatasetError` so the user gets a useful pointer

Validation errors include the source filename and the 1-indexed line
number so error messages survive long pipelines.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DatasetError(ValueError):
    """Raised when a dataset row fails schema validation."""

    def __init__(self, message: str, *, path: Path | None = None, line_no: int | None = None) -> None:
        prefix = ""
        if path is not None:
            prefix = f"{path}:"
            if line_no is not None:
                prefix = f"{path}:{line_no}: "
        elif line_no is not None:
            prefix = f"line {line_no}: "
        super().__init__(f"{prefix}{message}")
        self.path = path
        self.line_no = line_no


@dataclass(frozen=True)
class DatasetRow:
    """One dataset row, post-validation.

    ``raw`` keeps the original dict so callers (LangSmith / Phoenix
    adapters) can round-trip provider-specific fields without us having
    to teach the schema about every possible vendor extension.
    """

    row_id: str
    input: Any
    expected: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tags(self) -> list[str]:
        tags = self.metadata.get("tags") or []
        return [str(t) for t in tags] if isinstance(tags, list) else []

    @property
    def scorer(self) -> str | None:
        scorer = self.metadata.get("scorer")
        return str(scorer) if scorer else None

    @property
    def scorer_args(self) -> dict[str, Any]:
        args = self.metadata.get("scorer_args")
        return dict(args) if isinstance(args, dict) else {}


def parse_row(
    obj: dict[str, Any],
    *,
    line_no: int | None = None,
    path: Path | None = None,
    fallback_id: str | None = None,
) -> DatasetRow:
    """Validate and normalise a single JSON object into a :class:`DatasetRow`.

    Raises :class:`DatasetError` on schema violations.
    """
    if not isinstance(obj, dict):
        raise DatasetError(
            f"expected a JSON object, got {type(obj).__name__}",
            path=path,
            line_no=line_no,
        )
    if "input" not in obj:
        raise DatasetError("missing required field 'input'", path=path, line_no=line_no)

    metadata_raw = obj.get("metadata") or {}
    if not isinstance(metadata_raw, dict):
        raise DatasetError(
            f"'metadata' must be an object, got {type(metadata_raw).__name__}",
            path=path,
            line_no=line_no,
        )

    row_id = str(metadata_raw.get("id") or obj.get("id") or fallback_id or "")
    if not row_id:
        # Auto-id from the line number so callers never end up with empty IDs.
        row_id = f"row-{line_no or 0}"

    return DatasetRow(
        row_id=row_id,
        input=obj["input"],
        expected=obj.get("expected"),
        metadata=dict(metadata_raw),
        raw=dict(obj),
    )


def read_jsonl(path: str | Path) -> Iterator[DatasetRow]:
    """Yield :class:`DatasetRow` instances from a JSONL file.

    Blank lines and ``#``-prefixed lines are skipped. The function is a
    generator so very large datasets stream without buffering.
    """
    p = Path(path)
    if not p.exists():
        raise DatasetError(f"dataset not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetError(
                    f"invalid JSON: {exc.msg}",
                    path=p,
                    line_no=line_no,
                ) from exc
            yield parse_row(obj, line_no=line_no, path=p)


def load_jsonl(path: str | Path) -> list[DatasetRow]:
    """Eagerly load a JSONL dataset into memory.

    Convenience wrapper used by the runner; ``read_jsonl`` is preferred
    for very large datasets.
    """
    return list(read_jsonl(path))


def rows_from_objects(
    objects: list[dict[str, Any]], *, source: str | None = None
) -> list[DatasetRow]:
    """Adapt a list of plain dicts (e.g. pulled from LangSmith / Phoenix)
    into :class:`DatasetRow` instances.

    Used by adapter packages so they don't have to import internals.
    """
    source_path = Path(source) if source else None
    out: list[DatasetRow] = []
    for idx, obj in enumerate(objects, start=1):
        out.append(parse_row(obj, line_no=idx, path=source_path))
    return out


__all__ = [
    "DatasetError",
    "DatasetRow",
    "load_jsonl",
    "parse_row",
    "read_jsonl",
    "rows_from_objects",
]
