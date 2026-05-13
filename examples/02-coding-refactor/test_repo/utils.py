"""Class-based helpers — refactor target for the example.

Goal for the agent: rewrite ``Greeter`` as a small set of plain
functions (``make_greeter(prefix)`` returning a callable, or a pair
of free functions). The point is to show the agent reading the file,
proposing a hooks-style rewrite, and saving the edits back through the
sandboxed ``file_write`` tool.
"""

from __future__ import annotations


class Greeter:
    """A trivial stateful greeter — the OO style we want to replace."""

    def __init__(self, prefix: str = "Hello") -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix}, {name}!"

    def shout(self, name: str) -> str:
        return self.greet(name).upper()


__all__ = ["Greeter"]
