"""Tenant primitives for Wake.

Wake keeps the isolation boundary generic so product teams can map their own
customer/project/account model onto it. ``workspace_id`` is the operational
data boundary; ``organization_id`` groups one or more workspaces.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ORGANIZATION_ID = "default"
DEFAULT_WORKSPACE_ID = "default"


@dataclass(frozen=True)
class TenantContext:
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
