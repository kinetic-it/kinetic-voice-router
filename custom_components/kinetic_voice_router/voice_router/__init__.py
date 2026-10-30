"""Kinetic Voice Router - Entscheidungskern.

Reines Python ohne Home-Assistant-Import: deterministische Klassifikation,
Sitzungszustand im Arbeitsspeicher, Antwortpruefung. Experimentell, ohne Gewaehr.
"""

from .adapter import (
    BRIDGE_API_VERSION,
    BridgeReply,
    RouterBridge,
    failure_from_exception,
    simulate,
)
from .errors import classify_companion_error, normalize_chat_output
from .model import (
    ROUTER_VERSION,
    Clarification,
    ClarificationKind,
    Evidence,
    FailureCode,
    FailureSource,
    FailureSummary,
    Lane,
    ReasonCode,
    RouteDecision,
    RouteInput,
)
from .router import OperatingMode, RouterConfig, operating_mode, route, should_route
from .state import SessionStore
from .stats import RuntimeStats

__all__ = [
    "BRIDGE_API_VERSION",
    "OperatingMode",
    "RuntimeStats",
    "operating_mode",
    "simulate",
    "BridgeReply",
    "RouterBridge",
    "failure_from_exception",
    "ROUTER_VERSION",
    "Clarification",
    "ClarificationKind",
    "Evidence",
    "FailureCode",
    "FailureSource",
    "FailureSummary",
    "Lane",
    "ReasonCode",
    "RouteDecision",
    "RouteInput",
    "RouterConfig",
    "SessionStore",
    "classify_companion_error",
    "normalize_chat_output",
    "route",
    "should_route",
]
