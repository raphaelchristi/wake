"""Coding-refactor integration test.

Exercises the tools + sandbox slices end-to-end: an agent with bash
and file tools edits a small Python module in a workspace. Skipped
unless ``ANTHROPIC_API_KEY`` is present and Docker is available (the
default sandbox backend in Phase 1).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from wake.cli.client import WakeClient

pytestmark = [pytest.mark.integration]

REFACTOR_INSTRUCTION = (
    "Rewrite the Greeter class in utils.py as a pair of plain functions "
    "(make_greeter(prefix) returning a callable, plus shout()). "
    "Update main.py accordingly."
)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.usefixtures("require_anthropic_key")
def test_refactor_agent_runs(
    wake_client: WakeClient,
    tmp_path: Path,
) -> None:
    if not _docker_available():
        pytest.skip("docker not available; sandboxed tools require it.")

    repo_dir = Path(__file__).resolve().parents[2] / "examples" / "02-coding-refactor" / "test_repo"
    if not repo_dir.exists():
        pytest.skip(f"example repo missing at {repo_dir}")

    workspace = tmp_path / "workspace"
    shutil.copytree(repo_dir, workspace)

    agent = wake_client.create_agent(
        name="refactor-test",
        model="claude-opus-4-7",
        system="You refactor Python code with the available tools.",
        tools=["bash", "file_read", "file_write", "file_edit"],
    )
    session = wake_client.create_session(agent_id=agent["id"])
    wake_client.send_message(
        session["id"],
        f"{REFACTOR_INSTRUCTION} Workspace root: {workspace}",
    )

    deadline = time.monotonic() + 120.0
    saw_tool_use = False
    saw_assistant_message = False
    while time.monotonic() < deadline:
        events = wake_client.list_events(session["id"])
        for event in events:
            if event.get("type") == "tool_use":
                saw_tool_use = True
            if event.get("type") == "assistant.message":
                saw_assistant_message = True
        if saw_tool_use and saw_assistant_message:
            break
        time.sleep(0.5)
    assert saw_tool_use, "expected at least one tool_use event"
    assert saw_assistant_message, "expected an assistant.message before timeout"
