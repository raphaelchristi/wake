"""Built-in scorers + entry-point plugin discovery.

A scorer is anything that implements::

    score(*, output, expected, row, **kwargs) -> ScorerResult

We ship three:

* ``exact_match`` — string equality (with optional ``case_sensitive`` /
  ``strip`` flags). Useful for golden-output style datasets.
* ``regex`` — re.search() against the output. Pattern can come either
  from ``scorer_args.pattern`` or — convenient default — from the
  row's ``expected`` field.
* ``llm_judge`` — delegates to an LLM via ``litellm.completion`` (or an
  injected callable, used by tests). The judge prompt is fixed and
  documented in :data:`LLM_JUDGE_PROMPT`; advanced users can subclass.

Third-party scorers register via Python entry points under
``wake.eval.scorers``. See ``docs/EVAL-FRAMEWORK.md`` for the plugin
contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from wake.eval.dataset import DatasetRow

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScorerResult:
    """One scorer's verdict.

    ``score`` is a float in ``[0.0, 1.0]`` — runners aggregate via mean.
    ``passed`` reflects a binary success/failure derived from
    ``score >= threshold`` (default ``1.0``); scorers that don't have a
    natural threshold should set ``passed = score >= 0.5``.

    ``details`` is the place to stash human-readable diagnostics —
    runners include it verbatim in the markdown report.
    """

    name: str
    score: float
    passed: bool
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scorer protocol + base class
# ---------------------------------------------------------------------------


@runtime_checkable
class Scorer(Protocol):
    """Callable scorer interface.

    ``name`` is used by the runner to identify the scorer in reports and
    to register entry-point plugins. ``score`` MUST return a
    :class:`ScorerResult` even on failure (catch internal exceptions
    and surface them via ``details``); raising lets the runner mark the
    whole row as errored.
    """

    name: str

    def score(
        self,
        *,
        output: Any,
        expected: Any,
        row: DatasetRow,
        **kwargs: Any,
    ) -> ScorerResult: ...


class _BaseScorer:
    """Concrete-friendly mixin so subclasses get ``name``/repr for free."""

    name: str

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"{type(self).__name__}(name={self.name!r})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_text(value: Any) -> str:
    """Pull a string out of arbitrary output shapes.

    Wake events carry text inside ``payload.content[].text`` blocks; we
    accept either that shape, plain strings, or dicts with a ``text``
    key. Anything else falls back to ``str()``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
        content = value.get("content")
        if isinstance(content, list):
            chunks: list[str] = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    chunks.append(block["text"])
                elif isinstance(block, str):
                    chunks.append(block)
            if chunks:
                return "\n".join(chunks)
        return str(value)
    return str(value)


# ---------------------------------------------------------------------------
# exact_match
# ---------------------------------------------------------------------------


class ExactMatchScorer(_BaseScorer):
    name = "exact_match"

    def score(
        self,
        *,
        output: Any,
        expected: Any,
        row: DatasetRow,
        case_sensitive: bool = True,
        strip: bool = True,
        **_: Any,
    ) -> ScorerResult:
        if expected is None:
            return ScorerResult(
                name=self.name,
                score=0.0,
                passed=False,
                details="exact_match requires 'expected' but it was null",
            )
        out_str = _coerce_text(output)
        exp_str = _coerce_text(expected)
        if strip:
            out_str = out_str.strip()
            exp_str = exp_str.strip()
        if not case_sensitive:
            out_str = out_str.lower()
            exp_str = exp_str.lower()
        ok = out_str == exp_str
        return ScorerResult(
            name=self.name,
            score=1.0 if ok else 0.0,
            passed=ok,
            details="ok" if ok else f"expected={exp_str!r} got={out_str!r}",
        )


# ---------------------------------------------------------------------------
# regex
# ---------------------------------------------------------------------------


class RegexScorer(_BaseScorer):
    name = "regex"

    def score(
        self,
        *,
        output: Any,
        expected: Any,
        row: DatasetRow,
        pattern: str | None = None,
        flags: int | str = 0,
        **_: Any,
    ) -> ScorerResult:
        # Pattern resolution: explicit arg > expected field > error.
        eff_pattern = pattern if pattern is not None else (
            expected if isinstance(expected, str) else None
        )
        if not eff_pattern:
            return ScorerResult(
                name=self.name,
                score=0.0,
                passed=False,
                details="regex requires a pattern (via scorer_args.pattern or expected)",
            )
        eff_flags = _parse_regex_flags(flags)
        try:
            rx = re.compile(eff_pattern, eff_flags)
        except re.error as exc:
            return ScorerResult(
                name=self.name,
                score=0.0,
                passed=False,
                details=f"invalid regex {eff_pattern!r}: {exc}",
            )
        haystack = _coerce_text(output)
        match = rx.search(haystack)
        ok = match is not None
        details = f"match={match.group(0)!r}" if match else "no match"
        return ScorerResult(
            name=self.name,
            score=1.0 if ok else 0.0,
            passed=ok,
            details=details,
            metadata={"pattern": eff_pattern},
        )


def _parse_regex_flags(flags: int | str) -> int:
    if isinstance(flags, int):
        return flags
    if not flags:
        return 0
    mapping = {
        "I": re.IGNORECASE,
        "IGNORECASE": re.IGNORECASE,
        "M": re.MULTILINE,
        "MULTILINE": re.MULTILINE,
        "S": re.DOTALL,
        "DOTALL": re.DOTALL,
        "X": re.VERBOSE,
        "VERBOSE": re.VERBOSE,
    }
    acc = 0
    for token in str(flags).replace(",", "|").split("|"):
        token = token.strip().upper()
        if not token:
            continue
        if token not in mapping:
            raise ValueError(f"unknown regex flag: {token}")
        acc |= mapping[token]
    return acc


# ---------------------------------------------------------------------------
# llm_judge
# ---------------------------------------------------------------------------

LLM_JUDGE_PROMPT = """You are an impartial grading assistant. Given the
EXPECTED answer and the ACTUAL answer to a prompt, decide whether the
ACTUAL answer is correct.

Respond with a single JSON object on one line, no other prose:

    {"score": <0.0-1.0>, "passed": <true|false>, "reason": "<short>"}

Score 1.0 = essentially equivalent; 0.5 = partially correct;
0.0 = wrong. ``passed`` should be true iff score >= 0.7.
"""


class LLMJudgeScorer(_BaseScorer):
    """LLM-as-judge scorer.

    The ``judge_fn`` callable receives a single prompt string and must
    return a string. We try to parse a JSON object with ``score``,
    ``passed``, ``reason`` keys; failures fall back to ``score=0.0``
    with details containing the raw judge output (so debugging is
    obvious).

    Real-world callers should pass ``judge_fn=litellm_completion(...)``
    or similar — see ``docs/EVAL-FRAMEWORK.md`` for a recipe. The
    default factory imports ``litellm`` lazily so the dependency is
    optional.
    """

    name = "llm_judge"

    def __init__(self, judge_fn: Any | None = None, *, judge_model: str = "claude-haiku-4") -> None:
        self._judge_fn = judge_fn
        self._judge_model = judge_model

    def _default_judge(self, prompt: str) -> str:
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover — optional dep
            raise RuntimeError(
                "llm_judge requires litellm (install with `pip install litellm`) "
                "or pass an explicit judge_fn"
            ) from exc
        response = litellm.completion(  # type: ignore[attr-defined]
            model=self._judge_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        # litellm normalises to OpenAI shape.
        return str(response.choices[0].message.content)  # type: ignore[index]

    def score(
        self,
        *,
        output: Any,
        expected: Any,
        row: DatasetRow,
        judge_fn: Any | None = None,
        prompt: str | None = None,
        threshold: float = 0.7,
        **_: Any,
    ) -> ScorerResult:
        fn = judge_fn or self._judge_fn or self._default_judge
        eff_prompt = (
            (prompt or LLM_JUDGE_PROMPT)
            + f"\n\nEXPECTED:\n{_coerce_text(expected)}\n\nACTUAL:\n{_coerce_text(output)}\n"
        )
        try:
            raw = fn(eff_prompt) if callable(fn) else str(fn)
        except Exception as exc:  # noqa: BLE001 — surface as scorer failure
            return ScorerResult(
                name=self.name,
                score=0.0,
                passed=False,
                details=f"judge_fn raised {type(exc).__name__}: {exc}",
            )
        score, passed, reason = _parse_judge_response(raw, threshold=threshold)
        return ScorerResult(
            name=self.name,
            score=score,
            passed=passed,
            details=reason or raw[:200],
            metadata={"raw": raw},
        )


def _parse_judge_response(raw: str, *, threshold: float) -> tuple[float, bool, str]:
    import json

    text = (raw or "").strip()
    # Trim code fences if the judge wrapped JSON in ```json ... ```.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # Look for the first {...} blob.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return 0.0, False, f"unparseable judge output: {raw[:120]!r}"
    blob = text[start : end + 1]
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return 0.0, False, f"invalid JSON in judge output: {blob[:120]!r}"
    try:
        score_f = float(parsed.get("score", 0.0))
    except (TypeError, ValueError):
        score_f = 0.0
    score_f = max(0.0, min(1.0, score_f))
    raw_passed = parsed.get("passed")
    passed = bool(raw_passed) if raw_passed is not None else score_f >= threshold
    reason = str(parsed.get("reason") or "")
    return score_f, passed, reason


# ---------------------------------------------------------------------------
# Registry / plugin discovery
# ---------------------------------------------------------------------------


_BUILTIN: dict[str, Scorer] = {
    "exact_match": ExactMatchScorer(),
    "regex": RegexScorer(),
    "llm_judge": LLMJudgeScorer(),
}


class ScorerRegistry:
    """Combines built-in scorers with entry-point plugins.

    Plugins register via ``wake.eval.scorers`` entry points. Each entry
    point must resolve to either a scorer instance or a zero-arg
    callable that returns one. Duplicate registration replaces the
    built-in for that name — third-party authors are responsible for
    not clashing with shipped names unless they intend to.
    """

    def __init__(self, *, autodiscover: bool = True) -> None:
        self._scorers: dict[str, Scorer] = dict(_BUILTIN)
        if autodiscover:
            self._discover()

    def _discover(self) -> None:
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover — py <3.10 unreachable here
            return
        try:
            eps = entry_points(group="wake.eval.scorers")
        except TypeError:  # pragma: no cover — old API
            eps = entry_points().get("wake.eval.scorers", [])  # type: ignore[attr-defined]
        for ep in eps:
            try:
                obj = ep.load()
                scorer = obj() if callable(obj) and not isinstance(obj, type(_BUILTIN["exact_match"])) else obj
                if not hasattr(scorer, "score"):
                    continue
                self._scorers[ep.name] = scorer
            except Exception:  # noqa: BLE001 — broken plugin shouldn't kill the runner
                continue

    def register(self, scorer: Scorer) -> None:
        self._scorers[scorer.name] = scorer

    def get(self, name: str) -> Scorer:
        try:
            return self._scorers[name]
        except KeyError as exc:
            raise KeyError(
                f"unknown scorer {name!r}; registered: {sorted(self._scorers)}"
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._scorers)


def default_registry() -> ScorerRegistry:
    """Return a fresh registry with built-ins + discovered plugins."""
    return ScorerRegistry(autodiscover=True)


__all__ = [
    "ExactMatchScorer",
    "LLMJudgeScorer",
    "LLM_JUDGE_PROMPT",
    "RegexScorer",
    "Scorer",
    "ScorerRegistry",
    "ScorerResult",
    "default_registry",
]
