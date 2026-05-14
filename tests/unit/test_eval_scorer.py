"""Tests for ``wake.eval.scorer``.

Covers built-in scorers (exact_match / regex / llm_judge), the
``ScorerRegistry`` and plugin discovery, and parsing of LLM judge
responses (both well-formed and noisy).
"""

from __future__ import annotations

import re

import pytest

from wake.eval.dataset import parse_row
from wake.eval.scorer import (
    ExactMatchScorer,
    LLMJudgeScorer,
    RegexScorer,
    ScorerRegistry,
    ScorerResult,
    _parse_judge_response,
    default_registry,
)


def _row(input: str = "x", expected=None, metadata: dict | None = None):  # type: ignore[no-untyped-def]
    return parse_row(
        {"input": input, "expected": expected, "metadata": metadata or {}},
        line_no=1,
    )


# ---------------------------------------------------------------------------
# exact_match
# ---------------------------------------------------------------------------


def test_exact_match_hit() -> None:
    scorer = ExactMatchScorer()
    row = _row(expected="42")
    result = scorer.score(output="42", expected="42", row=row)
    assert isinstance(result, ScorerResult)
    assert result.passed is True
    assert result.score == 1.0


def test_exact_match_miss_includes_details() -> None:
    scorer = ExactMatchScorer()
    row = _row(expected="42")
    result = scorer.score(output="41", expected="42", row=row)
    assert result.passed is False
    assert result.score == 0.0
    assert "expected='42'" in result.details


def test_exact_match_strip_and_case_insensitive() -> None:
    scorer = ExactMatchScorer()
    row = _row(expected="HELLO")
    result = scorer.score(
        output="  hello  ", expected="HELLO", row=row, case_sensitive=False, strip=True
    )
    assert result.passed is True


def test_exact_match_with_text_block_output() -> None:
    scorer = ExactMatchScorer()
    row = _row(expected="ok")
    nested = {"content": [{"type": "text", "text": "ok"}]}
    result = scorer.score(output=nested, expected="ok", row=row)
    assert result.passed is True


def test_exact_match_null_expected_fails_cleanly() -> None:
    scorer = ExactMatchScorer()
    row = _row(expected=None)
    result = scorer.score(output="anything", expected=None, row=row)
    assert result.passed is False
    assert "requires 'expected'" in result.details


# ---------------------------------------------------------------------------
# regex
# ---------------------------------------------------------------------------


def test_regex_match_pattern_from_expected() -> None:
    scorer = RegexScorer()
    row = _row(expected=r"\d+")
    result = scorer.score(output="answer is 42", expected=r"\d+", row=row)
    assert result.passed is True
    assert "match='42'" in result.details


def test_regex_no_pattern_fails() -> None:
    scorer = RegexScorer()
    row = _row(expected=None)
    result = scorer.score(output="foo", expected=None, row=row)
    assert result.passed is False
    assert "requires a pattern" in result.details


def test_regex_pattern_via_kwargs_with_string_flag() -> None:
    scorer = RegexScorer()
    row = _row()
    result = scorer.score(
        output="HELLO WORLD",
        expected=None,
        row=row,
        pattern="hello",
        flags="IGNORECASE",
    )
    assert result.passed is True


def test_regex_no_match() -> None:
    scorer = RegexScorer()
    row = _row(expected=r"^foo")
    result = scorer.score(output="bar", expected=r"^foo", row=row)
    assert result.passed is False
    assert "no match" in result.details


def test_regex_invalid_pattern_handled() -> None:
    scorer = RegexScorer()
    row = _row(expected="(unbalanced")
    result = scorer.score(output="x", expected="(unbalanced", row=row)
    assert result.passed is False
    assert "invalid regex" in result.details


# ---------------------------------------------------------------------------
# llm_judge
# ---------------------------------------------------------------------------


def test_llm_judge_with_inline_fn_passes() -> None:
    def judge(prompt: str) -> str:
        # Should mention both expected and actual in the prompt body.
        assert "EXPECTED:" in prompt
        assert "ACTUAL:" in prompt
        return '{"score": 0.95, "passed": true, "reason": "synonym match"}'

    scorer = LLMJudgeScorer(judge_fn=judge)
    row = _row(expected="capital of France")
    result = scorer.score(output="Paris", expected="capital of France", row=row)
    assert result.passed is True
    assert result.score == pytest.approx(0.95)
    assert "synonym" in result.details


def test_llm_judge_threshold_overrides_passed() -> None:
    scorer = LLMJudgeScorer(judge_fn=lambda _p: '{"score": 0.4}')
    row = _row(expected="x")
    result = scorer.score(output="y", expected="x", row=row, threshold=0.5)
    assert result.passed is False
    assert result.score == pytest.approx(0.4)


def test_llm_judge_unparseable_falls_back() -> None:
    scorer = LLMJudgeScorer(judge_fn=lambda _p: "I am not JSON, sorry")
    row = _row(expected="x")
    result = scorer.score(output="y", expected="x", row=row)
    assert result.passed is False
    assert result.score == 0.0
    assert "unparseable" in result.details


def test_llm_judge_judge_fn_exception_captured() -> None:
    def boom(_p: str) -> str:
        raise RuntimeError("API outage")

    scorer = LLMJudgeScorer(judge_fn=boom)
    row = _row(expected="x")
    result = scorer.score(output="y", expected="x", row=row)
    assert result.passed is False
    assert "API outage" in result.details


def test_parse_judge_response_strips_code_fences() -> None:
    raw = "```json\n{\"score\": 1.0, \"passed\": true, \"reason\": \"ok\"}\n```"
    score, passed, reason = _parse_judge_response(raw, threshold=0.7)
    assert score == 1.0
    assert passed is True
    assert reason == "ok"


def test_parse_judge_response_clips_score() -> None:
    score, _, _ = _parse_judge_response('{"score": 5.0}', threshold=0.5)
    assert score == 1.0
    score, _, _ = _parse_judge_response('{"score": -1.0}', threshold=0.5)
    assert score == 0.0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_default_registry_lists_builtins() -> None:
    reg = default_registry()
    assert "exact_match" in reg.names()
    assert "regex" in reg.names()
    assert "llm_judge" in reg.names()


def test_registry_register_overrides() -> None:
    class FakeScorer:
        name = "fake"

        def score(self, **_: object) -> ScorerResult:
            return ScorerResult(name=self.name, score=1.0, passed=True)

    reg = ScorerRegistry(autodiscover=False)
    fake = FakeScorer()
    reg.register(fake)
    assert reg.get("fake") is fake


def test_registry_get_unknown_raises() -> None:
    reg = ScorerRegistry(autodiscover=False)
    with pytest.raises(KeyError, match="unknown scorer"):
        reg.get("does-not-exist")
