"""Tiny CLI module — entry point used by the refactor example.

The agent's job in this example is to convert the class-based
``Greeter`` implementation in :mod:`utils` into a pair of pure
functions (a closure-free, hook-style refactor), then update this
module to import the new shape.

Currently uses the class form, which is exactly what we want it to
rewrite.
"""

from __future__ import annotations

import sys

from utils import Greeter


def main(argv: list[str]) -> int:
    name = argv[1] if len(argv) > 1 else "world"
    greeter = Greeter(prefix="Hello")
    print(greeter.greet(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
