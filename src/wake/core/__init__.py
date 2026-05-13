"""Wake core domain.

Bridges raw storage (`wake.store`) with higher-level domain operations:
agent versioning, environment management, session lifecycle (state
machine), and the event log API.

Modules here own *business logic*; storage primitives stay in
``wake.store``.
"""

from wake.core.agent import AgentService
from wake.core.environment import EnvironmentService
from wake.core.event_log import EventLog
from wake.core.session import (
    InvalidTransitionError,
    SessionService,
)

__all__ = [
    "AgentService",
    "EnvironmentService",
    "EventLog",
    "SessionService",
    "InvalidTransitionError",
]
