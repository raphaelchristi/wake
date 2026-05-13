"""Wake CLI — `wake` command-line interface.

Talks to a running Wake server over HTTP. By default, points at
http://localhost:8080 — override via the ``WAKE_SERVER`` environment
variable.

The CLI itself imports nothing from the runtime/foundation slices at
import time (only ``wake.types`` for shared schemas), and reaches the
server through :class:`wake.cli.client.WakeClient`.
"""

from __future__ import annotations

__all__: list[str] = []
