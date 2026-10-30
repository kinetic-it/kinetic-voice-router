"""Typen des Kinetic Voice Router.

Reine Datentypen ohne Seiteneffekte. Keine Netz-, Datei- oder HA-Zugriffe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

ROUTER_VERSION = "0.5.0b1"


class Lane(StrEnum):
    """Die vier zulaessigen Routing-Spuren."""

    CHAT = "CHAT"
    CONTROL_FALLBACK = "CONTROL_FALLBACK"
    EXPLAIN_LAST = "EXPLAIN_LAST"
    UNKNOWN = "UNKNOWN"


class ReasonCode(StrEnum):
    """Maschinenlesbarer Grund einer Routing-Entscheidung."""

    # CHAT
    KNOWLEDGE_QUESTION = "KNOWLEDGE_QUESTION"
    CONVERSATION = "CONVERSATION"
    # CONTROL_FALLBACK
    ACTION_LIKE_WITHOUT_EXECUTION = "ACTION_LIKE_WITHOUT_EXECUTION"
    CAPABILITY_QUESTION = "CAPABILITY_QUESTION"
    CONFIRMATION_WITHOUT_EXECUTION_PATH = "CONFIRMATION_WITHOUT_EXECUTION_PATH"
    STATUS_QUERY_WITHOUT_VERIFIED_ACCESS = "STATUS_QUERY_WITHOUT_VERIFIED_ACCESS"
    # EXPLAIN_LAST
    EXPLICIT_DEBUG_VERIFIED = "EXPLICIT_DEBUG_VERIFIED"
    EXPLICIT_DEBUG_NO_EVIDENCE = "EXPLICIT_DEBUG_NO_EVIDENCE"
    # UNKNOWN
    EMPTY_INPUT = "EMPTY_INPUT"
    INPUT_TOO_LONG = "INPUT_TOO_LONG"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    AMBIGUOUS_FRAGMENT = "AMBIGUOUS_FRAGMENT"
    AMBIGUOUS_MIXED = "AMBIGUOUS_MIXED"
    BARE_CONFIRMATION = "BARE_CONFIRMATION"
    CLARIFICATION_DECLINED = "CLARIFICATION_DECLINED"
    UNCLASSIFIED = "UNCLASSIFIED"
    # Schutz, falls der Router trotz lokaler HA-Behandlung aufgerufen wird
    LOCAL_ALREADY_HANDLED = "LOCAL_ALREADY_HANDLED"


class Evidence(StrEnum):
    """Belegstaerke einer Diagnose-Aussage."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NONE = "NONE"


class FailureCode(StrEnum):
    """Bereinigte Fehlerklassen."""

    ACTION_LIKE_UNHANDLED = "ACTION_LIKE_UNHANDLED"
    STATUS_NOT_AVAILABLE = "STATUS_NOT_AVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    HA_UNREACHABLE = "HA_UNREACHABLE"
    ENTITY_NOT_EXPOSED = "ENTITY_NOT_EXPOSED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


# Diese Klassen duerfen nur aus einem ausdruecklichen HA-Beleg stammen.
HA_ONLY_CODES = frozenset({FailureCode.HA_UNREACHABLE, FailureCode.ENTITY_NOT_EXPOSED})


class FailureSource(StrEnum):
    HA = "HA"
    HERMES_COMPANION = "HERMES_COMPANION"
    ROUTER = "ROUTER"
    UNKNOWN = "UNKNOWN"


class ClarificationKind(StrEnum):
    """Art der vorbereiteten Rueckfrage."""

    QUESTION_OR_DEVICE = "QUESTION_OR_DEVICE"
    ONE_THING_AT_A_TIME = "ONE_THING_AT_A_TIME"


@dataclass(frozen=True)
class FailureSummary:
    """Minimaler, nicht personenbezogener Fehlereintrag.

    Enthaelt bewusst keinen Wortlaut, keine Entitaet, keinen Raum, keinen Namen.
    """

    code: FailureCode
    source: FailureSource
    occurred_at_monotonic: float


@dataclass(frozen=True)
class Clarification:
    """Vorbereitete kurze Rueckfrage. Eine Antwort darauf loest nie eine Aktion aus."""

    kind: ClarificationKind
    question: str


@dataclass(frozen=True)
class RouteInput:
    utterance: object  # bewusst object: ungueltige Payloads muessen fail-closed sein
    language: str = "de"
    conversation_id: str | None = None
    local_handled: bool | None = None


@dataclass(frozen=True)
class RouteDecision:
    lane: Lane
    reason_code: ReasonCode
    rule_id: str
    response: str | None
    may_call_hermes: bool
    diagnostic_evidence: Evidence = Evidence.NONE
    clarification: Clarification | None = None
    explained_failure: FailureCode | None = None
    router_version: str = ROUTER_VERSION
    # Invariante: der Router fuehrt niemals Geraeteaktionen aus.
    may_call_ha_action: bool = field(default=False, init=False)

    def trace(self) -> dict[str, object]:
        """Nachvollziehbare, datensparsame Darstellung fuer Logs.

        Enthaelt niemals den Eingabetext oder die Conversation-ID.
        """
        return {
            "router_version": self.router_version,
            "lane": self.lane.value,
            "reason_code": self.reason_code.value,
            "rule_id": self.rule_id,
            "may_call_hermes": self.may_call_hermes,
            "may_call_ha_action": self.may_call_ha_action,
            "diagnostic_evidence": self.diagnostic_evidence.value,
            "clarification": self.clarification.kind.value if self.clarification else None,
            "explained_failure": self.explained_failure.value if self.explained_failure else None,
        }
