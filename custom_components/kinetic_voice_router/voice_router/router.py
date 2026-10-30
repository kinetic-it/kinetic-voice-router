"""Post-Local-Policy-Router des Kinetic Voice Router.

Entscheidet fuer Saetze, die Home Assistant nicht lokal erledigt hat, eine von
vier Spuren (CHAT, CONTROL_FALLBACK, EXPLAIN_LAST, UNKNOWN). Einbindung in
Gespraechsagenten ueber `adapter.RouterBridge`.

Der Router selbst fuehrt keine Aktion aus, ruft kein Netz und keine HA-API auf.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from . import responses
from .classify import Kind, classify, is_device_term, normalize
from .model import (
    Clarification,
    ClarificationKind,
    Evidence,
    FailureCode,
    FailureSource,
    Lane,
    ReasonCode,
    RouteDecision,
    RouteInput,
)
from .state import SessionStore

MAX_UTTERANCE_CHARS = 500
SUPPORTED_LANGUAGES = frozenset({"de"})


class OperatingMode(StrEnum):
    """Betriebsart (R3). OFF: Upstream-Pfad. OBSERVE: nur zaehlen. ACTIVE: routen."""

    OFF = "off"
    OBSERVE = "observe"
    ACTIVE = "active"


def operating_mode(options: Mapping[str, object] | None) -> OperatingMode:
    """Liest die Betriebsart fail-closed aus HA-Optionen.

    - gueltiges `mode` gewinnt;
    - ohne `mode` gilt das alte 0.3.0-Flag `router_enabled`: nur echtes True -> ACTIVE
      (ein bisher aktiver Router bleibt aktiv, nichts wird ungewollt eingeschaltet);
    - alles andere (fehlend, kaputt, unbekannt) -> OFF.
    """
    if not isinstance(options, Mapping):
        return OperatingMode.OFF
    if "mode" in options:
        value = options.get("mode")
        if isinstance(value, str) and value in {m.value for m in OperatingMode}:
            return OperatingMode(value)
        return OperatingMode.OFF
    return OperatingMode.ACTIVE if options.get("router_enabled") is True else OperatingMode.OFF


@dataclass(frozen=True)
class RouterConfig:
    """Routing an/aus fuer `route()`. Standard: deaktiviert."""

    router_enabled: bool = False

    @classmethod
    def from_mapping(cls, options: Mapping[str, object] | None) -> RouterConfig:
        """Fail-closed: nur Betriebsart ACTIVE (bzw. altes echtes `True`) routet."""
        return cls(router_enabled=operating_mode(options) is OperatingMode.ACTIVE)


def should_route(config: RouterConfig, route_input: RouteInput) -> bool:
    """Darf der Router fuer diese Anfrage ueberhaupt eingreifen?

    Nein bei deaktiviertem Flag oder wenn HA lokal bereits behandelt hat.
    """
    return config.router_enabled is True and route_input.local_handled is not True


def _decision(
    lane: Lane,
    reason: ReasonCode,
    rule_id: str,
    response: str | None,
    *,
    may_call_hermes: bool = False,
    evidence: Evidence = Evidence.NONE,
    clarification: Clarification | None = None,
    explained: FailureCode | None = None,
) -> RouteDecision:
    return RouteDecision(
        lane=lane,
        reason_code=reason,
        rule_id=rule_id,
        response=response,
        may_call_hermes=may_call_hermes,
        diagnostic_evidence=evidence,
        clarification=clarification,
        explained_failure=explained,
    )


def _ask(kind: ClarificationKind, reason: ReasonCode, rule_id: str) -> RouteDecision:
    question = responses.CLARIFICATION_TEXT[kind]
    return _decision(
        Lane.UNKNOWN, reason, rule_id, question, clarification=Clarification(kind, question)
    )


def route(
    route_input: RouteInput,
    store: SessionStore,
    config: RouterConfig | None = None,
) -> RouteDecision:
    """Entscheidet die Spur fuer eine an Hermes durchgereichte Anfrage.

    Reine Entscheidungslogik; einziger Seiteneffekt ist der kurzlebige,
    datensparsame Sitzungszustand im uebergebenen `store`.
    """
    if route_input.local_handled is True:
        return _decision(Lane.UNKNOWN, ReasonCode.LOCAL_ALREADY_HANDLED, "R-GUARD-LOCAL", None)

    text = route_input.utterance
    if not isinstance(text, str):
        return _decision(
            Lane.UNKNOWN, ReasonCode.INVALID_INPUT, "R-GUARD-TYPE", responses.NOT_UNDERSTOOD
        )
    if not isinstance(route_input.language, str) or (
        route_input.language.split("-")[0].lower() not in SUPPORTED_LANGUAGES
    ):
        return _decision(
            Lane.UNKNOWN,
            ReasonCode.UNSUPPORTED_LANGUAGE,
            "R-GUARD-LANG",
            responses.UNSUPPORTED_LANGUAGE,
        )
    if len(text) > MAX_UTTERANCE_CHARS:
        return _decision(
            Lane.UNKNOWN, ReasonCode.INPUT_TOO_LONG, "R-GUARD-LEN", responses.NOT_UNDERSTOOD
        )
    normalized = normalize(text)
    if not normalized:
        return _decision(
            Lane.UNKNOWN, ReasonCode.EMPTY_INPUT, "R-GUARD-EMPTY", responses.NOT_UNDERSTOOD
        )

    cid = route_input.conversation_id
    pending = store.pop_clarification(cid)
    result = classify(normalized)

    # Antwort auf eine offene Rueckfrage: niemals Ausfuehrung.
    if pending is not None and result.kind is Kind.CONFIRM:
        store.record_failure(cid, FailureCode.ACTION_LIKE_UNHANDLED, FailureSource.ROUTER)
        return _decision(
            Lane.CONTROL_FALLBACK,
            ReasonCode.CONFIRMATION_WITHOUT_EXECUTION_PATH,
            "R-CONFIRM-PENDING",
            responses.CONFIRMATION_NOT_EXECUTABLE,
        )
    if pending is not None and result.kind is Kind.DECLINE:
        return _decision(
            Lane.UNKNOWN, ReasonCode.CLARIFICATION_DECLINED, "R-DECLINE-PENDING", responses.DECLINED
        )

    kind = result.kind
    # These are confirmations/short words, not control acknowledgements.
    # Words such as "mach das", "schalten", "stopp" and "aus" must not be
    # promoted to a Hermes command just because the prior answer was a question.
    safe_acknowledgements = frozenset(
        {
            "ja",
            "jap",
            "jo",
            "genau",
            "richtig",
            "ja bitte",
            "ja genau",
            "nein",
            "nö",
            "ne",
            "nein danke",
        }
    )
    control_fragments = frozenset(
        {
            "an",
            "aus",
            "ein",
            "auf",
            "zu",
            "on",
            "off",
            "hoch",
            "runter",
            "heller",
            "dunkler",
            "lauter",
            "leiser",
        }
    )
    # A brief reply to a *verified* prior conversational question can reach Hermes.
    # Explicit control/status requests are never included; device-like fragments
    # and confirmations without a question remain on the existing safe path.
    if (
        route_input.chat_followup
        and kind in (Kind.FRAGMENT, Kind.CONFIRM, Kind.DECLINE)
        and len(normalized.split()) <= 2
        and not any(is_device_term(token) for token in normalized.split())
        and normalized not in control_fragments
        and (kind is Kind.FRAGMENT or normalized in safe_acknowledgements)
    ):
        if len(normalized) == 1 and normalized.isalpha():
            return _decision(
                Lane.UNKNOWN,
                ReasonCode.CHAT_FOLLOWUP_UNCLEAR,
                "R-FOLLOWUP-STT",
                responses.CHAT_FOLLOWUP_UNCLEAR,
            )
        return _decision(
            Lane.CHAT,
            ReasonCode.CHAT_FOLLOWUP,
            "R-FOLLOWUP-CHAT",
            None,
            may_call_hermes=True,
        )

    if kind is Kind.EXPLAIN_REQUEST:
        return _explain(store, cid, result.rule_id)

    if kind in (Kind.ACTION, Kind.POLITE_ACTION):
        store.record_failure(cid, FailureCode.ACTION_LIKE_UNHANDLED, FailureSource.ROUTER)
        return _decision(
            Lane.CONTROL_FALLBACK,
            ReasonCode.ACTION_LIKE_WITHOUT_EXECUTION,
            result.rule_id,
            responses.NOT_EXECUTED,
        )
    if kind is Kind.STATUS:
        # Kein verifizierter Statuszugriff: weder Hermes fragen noch einen Zustand erfinden.
        store.record_failure(cid, FailureCode.STATUS_NOT_AVAILABLE, FailureSource.ROUTER)
        return _decision(
            Lane.CONTROL_FALLBACK,
            ReasonCode.STATUS_QUERY_WITHOUT_VERIFIED_ACCESS,
            result.rule_id,
            responses.STATUS_NOT_AVAILABLE,
        )
    if kind is Kind.CAPABILITY:
        return _decision(
            Lane.CONTROL_FALLBACK,
            ReasonCode.CAPABILITY_QUESTION,
            result.rule_id,
            responses.CAPABILITY_UNSURE,
        )
    if kind is Kind.KNOWLEDGE:
        return _decision(
            Lane.CHAT, ReasonCode.KNOWLEDGE_QUESTION, result.rule_id, None, may_call_hermes=True
        )
    if kind is Kind.CHAT:
        return _decision(
            Lane.CHAT, ReasonCode.CONVERSATION, result.rule_id, None, may_call_hermes=True
        )

    if kind is Kind.MIXED:
        store.set_clarification(cid, ClarificationKind.ONE_THING_AT_A_TIME)
        return _ask(
            ClarificationKind.ONE_THING_AT_A_TIME, ReasonCode.AMBIGUOUS_MIXED, result.rule_id
        )
    if kind is Kind.FRAGMENT:
        store.set_clarification(cid, ClarificationKind.QUESTION_OR_DEVICE)
        return _ask(
            ClarificationKind.QUESTION_OR_DEVICE, ReasonCode.AMBIGUOUS_FRAGMENT, result.rule_id
        )
    if kind in (Kind.CONFIRM, Kind.DECLINE):
        # "Ja"/"Nein" ohne offene Rueckfrage: kein Kontext, keine Aktion
        return _decision(
            Lane.UNKNOWN, ReasonCode.BARE_CONFIRMATION, result.rule_id, responses.NOT_UNDERSTOOD
        )

    return _decision(Lane.UNKNOWN, ReasonCode.UNCLASSIFIED, "R-FALLBACK", responses.NOT_UNDERSTOOD)


def _explain(store: SessionStore, cid: str | None, rule_id: str) -> RouteDecision:
    failure = store.last_failure(cid)
    if failure is None:
        return _decision(
            Lane.EXPLAIN_LAST,
            ReasonCode.EXPLICIT_DEBUG_NO_EVIDENCE,
            rule_id,
            responses.NO_SAFE_REASON,
        )
    return _decision(
        Lane.EXPLAIN_LAST,
        ReasonCode.EXPLICIT_DEBUG_VERIFIED,
        rule_id,
        responses.FAILURE_TEXT[failure.code],
        evidence=Evidence.VERIFIED,
        explained=failure.code,
    )
