"""Sandbox state reconstruction from event log.

Replays a session's events deterministically from ``seq=0`` up to (inclusive)
a target ``seq`` and returns a minimal snapshot of the reconstructed sandbox
state plus running counters.

This is the engine behind ``GET /v1/sessions/{id}/state-at/{seq}``. Replay UIs
call it once per scrubber position; we keep the logic pure-function and free
of any external dependencies so it can be unit-tested with a list of plain
events.

The reconstructed state intentionally covers only what an operator needs at a
glance in the replay drawer:

- ``cwd``        — last ``cd <dir>`` extracted from ``bash`` tool calls
- ``last_output_lines`` — content of the most recent ``tool_result``
- ``files_modified`` — paths emitted by ``file_write`` / ``file_edit`` tools
- ``tool_calls_so_far``, ``errors_so_far`` — coarse counters for context

The function is intentionally tolerant: malformed/unknown payloads are skipped
rather than raised. A full forensic reconstruction is out of scope.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from wake.types import Event

# Cap the number of files we track to keep responses bounded for very long
# sessions; UI can request more via pagination later if needed.
_MAX_FILES_TRACKED = 200

# Cap output lines we keep verbatim in the snapshot.
_MAX_OUTPUT_LINES = 50

# Matches a leading ``cd <path>`` in a bash command. Tolerates leading
# whitespace and an optional ``builtin cd`` shell prefix. Anything compound
# like ``cd foo && bar`` only takes the first token (the directory).
_CD_RE = re.compile(r"^\s*(?:builtin\s+)?cd\s+(?P<path>\S+)")


@dataclass
class SandboxSnapshot:
    """Minimal sandbox state observed at a given seq."""

    cwd: str = "/"
    last_output_lines: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)


@dataclass
class ReconstructedState:
    """Full snapshot returned by ``reconstruct_state_at``."""

    seq: int
    sandbox: SandboxSnapshot
    tool_calls_so_far: int = 0
    errors_so_far: int = 0


def _normalize_cwd(current: str, target: str) -> str:
    """Resolve a ``cd`` argument against the current cwd (string-only).

    We don't have a real filesystem — this is a best-effort PWD model. We
    handle absolute paths, ``~``, ``..`` segments, and ``-`` (no-op, since
    we don't track OLDPWD).
    """
    if target == "-":
        return current
    if target.startswith("~"):
        # Treat ``~`` as ``/root`` (matches sandbox-runtime default).
        target = "/root" + target[1:]
    if target.startswith("/"):
        new = target
    else:
        new = current.rstrip("/") + "/" + target
    # Collapse ``a/./b`` and ``a/../b`` segments.
    parts: list[str] = []
    for seg in new.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts) if parts else "/"


def _extract_text(content: Any) -> str:
    """Pull text out of an Anthropic-style content blocks list.

    Accepts:
    - ``str`` (returned as-is)
    - ``list[dict]`` (concatenated ``text`` fields)
    - anything else → ``""``
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
        return "\n".join(chunks)
    return ""


def _add_file(files: list[str], path: str | None) -> None:
    if not path or not isinstance(path, str):
        return
    if path in files:
        # Move to end to indicate recency.
        files.remove(path)
    files.append(path)
    if len(files) > _MAX_FILES_TRACKED:
        # Drop the oldest entries (front of list).
        del files[: len(files) - _MAX_FILES_TRACKED]


def _apply_tool_use(state: ReconstructedState, payload: dict[str, Any]) -> None:
    state.tool_calls_so_far += 1
    name = payload.get("name")
    tool_input = payload.get("input") or {}
    if not isinstance(tool_input, dict):
        return

    if name == "bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            match = _CD_RE.match(command)
            if match:
                state.sandbox.cwd = _normalize_cwd(
                    state.sandbox.cwd, match.group("path")
                )
    elif name in {"file_write", "file_edit", "file_create"}:
        path = tool_input.get("path") or tool_input.get("file_path")
        _add_file(state.sandbox.files_modified, path)
    elif name == "write_file":
        # Some adapters use this alias.
        _add_file(
            state.sandbox.files_modified,
            tool_input.get("path") or tool_input.get("file_path"),
        )


def _apply_tool_result(state: ReconstructedState, payload: dict[str, Any]) -> None:
    if payload.get("is_error"):
        # Tool-level errors count as soft errors.
        state.errors_so_far += 1
    text = _extract_text(payload.get("content"))
    if text:
        lines = text.splitlines()
        if len(lines) > _MAX_OUTPUT_LINES:
            lines = lines[-_MAX_OUTPUT_LINES:]
        state.sandbox.last_output_lines = lines


def _apply_error(state: ReconstructedState) -> None:
    state.errors_so_far += 1


def reconstruct_state_at(events: list[Event], target_seq: int) -> ReconstructedState:
    """Replay events 0..target_seq (inclusive) and return the snapshot.

    ``events`` MUST be ordered by ``seq`` ascending. The function tolerates
    gaps (events with ``seq > target_seq`` are simply skipped).
    """
    state = ReconstructedState(seq=target_seq, sandbox=SandboxSnapshot())
    for ev in events:
        if ev.seq > target_seq:
            break
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        if ev.type == "tool_use":
            _apply_tool_use(state, payload)
        elif ev.type == "tool_result":
            _apply_tool_result(state, payload)
        elif ev.type == "error":
            _apply_error(state)
    return state


def parse_bash_cd(command: str) -> str | None:
    """Public helper exposed for tests / introspection."""
    match = _CD_RE.match(command)
    return match.group("path") if match else None


# Helpful for the command parser if a future caller wants to splitext args.
def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()
