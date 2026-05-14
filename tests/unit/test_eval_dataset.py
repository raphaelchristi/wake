"""Tests for ``wake.eval.dataset``.

Exercises JSONL parsing, schema validation, the ``DatasetRow`` helper
properties, and the ``rows_from_objects`` adapter used by LangSmith /
Phoenix drivers. The tests stick to pure-Python (tmp_path) so they
run without any IO mocks.
"""

from __future__ import annotations

import pytest

from wake.eval.dataset import (
    DatasetError,
    DatasetRow,
    load_jsonl,
    parse_row,
    read_jsonl,
    rows_from_objects,
)


# ---------------------------------------------------------------------------
# parse_row
# ---------------------------------------------------------------------------


def test_parse_row_minimum_fields() -> None:
    row = parse_row({"input": "hi"}, line_no=1)
    assert isinstance(row, DatasetRow)
    assert row.row_id == "row-1"
    assert row.input == "hi"
    assert row.expected is None
    assert row.metadata == {}
    assert row.raw == {"input": "hi"}


def test_parse_row_with_metadata_id() -> None:
    row = parse_row(
        {
            "input": "what is 1+1",
            "expected": "2",
            "metadata": {
                "id": "math-001",
                "tags": ["arithmetic", "smoke"],
                "scorer": "regex",
                "scorer_args": {"pattern": r"^2"},
            },
        },
        line_no=42,
    )
    assert row.row_id == "math-001"
    assert row.tags == ["arithmetic", "smoke"]
    assert row.scorer == "regex"
    assert row.scorer_args == {"pattern": r"^2"}


def test_parse_row_missing_input_raises() -> None:
    with pytest.raises(DatasetError, match="missing required field 'input'"):
        parse_row({"expected": "x"}, line_no=3)


def test_parse_row_non_dict_raises() -> None:
    with pytest.raises(DatasetError, match="expected a JSON object"):
        parse_row("not a dict", line_no=1)  # type: ignore[arg-type]


def test_parse_row_bad_metadata_type_raises() -> None:
    with pytest.raises(DatasetError, match="'metadata' must be an object"):
        parse_row({"input": "x", "metadata": "bad"}, line_no=1)


def test_dataset_row_tags_filters_non_lists() -> None:
    row = parse_row({"input": "x", "metadata": {"tags": "not-a-list"}}, line_no=1)
    assert row.tags == []


# ---------------------------------------------------------------------------
# read_jsonl / load_jsonl
# ---------------------------------------------------------------------------


def _write(p, content):  # type: ignore[no-untyped-def]
    p.write_text(content, encoding="utf-8")
    return p


def test_read_jsonl_skips_blanks_and_comments(tmp_path):  # type: ignore[no-untyped-def]
    f = _write(
        tmp_path / "ds.jsonl",
        "\n"
        "# a comment\n"
        '{"input": "hello", "expected": "world"}\n'
        "\n"
        '{"input": "foo"}\n',
    )
    rows = list(read_jsonl(f))
    assert len(rows) == 2
    assert rows[0].input == "hello"
    assert rows[0].expected == "world"
    assert rows[1].input == "foo"


def test_read_jsonl_invalid_json_includes_line(tmp_path):  # type: ignore[no-untyped-def]
    f = _write(tmp_path / "bad.jsonl", '{"input": "ok"}\n{not json}\n')
    with pytest.raises(DatasetError) as exc_info:
        list(read_jsonl(f))
    # The path and line number must appear in the error.
    assert "bad.jsonl" in str(exc_info.value)
    assert exc_info.value.line_no == 2


def test_read_jsonl_missing_file_raises(tmp_path):  # type: ignore[no-untyped-def]
    with pytest.raises(DatasetError, match="not found"):
        list(read_jsonl(tmp_path / "missing.jsonl"))


def test_load_jsonl_returns_list(tmp_path):  # type: ignore[no-untyped-def]
    f = _write(tmp_path / "ds.jsonl", '{"input": "a"}\n{"input": "b"}\n')
    rows = load_jsonl(f)
    assert isinstance(rows, list)
    assert [r.input for r in rows] == ["a", "b"]


# ---------------------------------------------------------------------------
# rows_from_objects
# ---------------------------------------------------------------------------


def test_rows_from_objects_assigns_ids() -> None:
    rows = rows_from_objects(
        [
            {"input": "x", "expected": "y"},
            {"input": "p", "metadata": {"id": "explicit"}},
        ],
        source="langsmith://dataset/golden",
    )
    assert [r.row_id for r in rows] == ["row-1", "explicit"]


def test_rows_from_objects_validates_each() -> None:
    with pytest.raises(DatasetError):
        rows_from_objects([{"expected": "missing input"}])
