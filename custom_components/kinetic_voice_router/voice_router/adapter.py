"""Schnittstelle des Router-Kerns fuer den Gespraechsagenten der Integration.

Die ConversationEntity (conversation.py) uebergibt Text, Sprache, Sitzungsschluessel
und eine Funktion, die den Hermes-Aufruf ausfuehrt; der Router entscheidet, ob diese
Funktion aufgerufen wird. Kein Home-Assistant-Import in diesem Paket.

Ausserhalb der Betriebsart ACTIVE liefert `async_handle` None: der Aufrufer fragt dann
Hermes unveraendert. Im aktiven Modus wirft `async_handle` bei eigenen Fehlern nicht,
sondern antwortet neutral (fail-closed, kein stiller Bypass).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from . import responses
from .classify import is_narrative_request
from .errors import classify_companion_error, normalize_chat_output
from .model import FailureCode, FailureSource, Lane, ReasonCode, RouteDecision, RouteInput
from .router import OperatingMode, RouterConfig, operating_mode, route, should_route
from .state import SessionStore
from .stats import RuntimeStats

# Ausnahmeklassen des Hermes-Clients (hermes_client.py), per Klassenname statt Import,
# damit der Router-Kern ohne die Integration testbar bleibt.
_ERROR_CLASS_MAP: dict[str, FailureCode] = {
    "AuthenticationError": FailureCode.AUTH_FAILED,
    "CapabilityUnavailableError": FailureCode.PROVIDER_UNAVAILABLE,
    "CannotConnectError": FailureCode.PROVIDER_UNAVAILABLE,
}


def failure_from_exception(err: BaseException) -> FailureCode:
    """Ordnet einen Fehler des Hermes-Aufrufs einer sicheren Klasse zu.

    Liefert nie HA_UNREACHABLE oder ENTITY_NOT_EXPOSED: der Aufruf geht an den
    Companion, nicht an Home Assistant.
    """
    if isinstance(err, TimeoutError) or isinstance(err.__cause__, TimeoutError):
        return FailureCode.PROVIDER_TIMEOUT
    code = getattr(err, "code", None)
    status = getattr(err, "status", None)
    if code is not None or status is not None:
        return classify_companion_error(code, status)
    for cls in type(err).__mro__:
        if cls.__name__ in _ERROR_CLASS_MAP:
            return _ERROR_CLASS_MAP[cls.__name__]
    return FailureCode.UNKNOWN_FAILURE


# Feste Entscheidung fuer einen internen Routerfehler im aktiven Modus: keine
# Weitergabe an Hermes, keine Aktion, keine Eingabedaten.
ROUTER_FAILURE_DECISION = RouteDecision(
    lane=Lane.UNKNOWN,
    reason_code=ReasonCode.UNCLASSIFIED,
    rule_id="R-GUARD-ERROR",
    response=None,
    may_call_hermes=False,
)


@dataclass(frozen=True)
class BridgeReply:
    """Ergebnis fuer die Entity: sprechbarer Text und ob HA ihn als Fehler melden soll."""

    text: str
    is_error: bool
    hermes_called: bool
    decision: RouteDecision


# Version des Vertrags zwischen Router und Aufrufer. Aufrufer greifen nur bei
# exakt dieser Version ein, sonst bisheriger Pfad.
#   1 (R2): enabled, async_handle
#   2 (R3): zusaetzlich mode, observing, observe(); enabled nur in Betriebsart ACTIVE
BRIDGE_API_VERSION = 2


class RouterBridge:
    """Eine Instanz je Config-Eintrag; haelt den kurzlebigen SessionStore."""

    api_version = BRIDGE_API_VERSION

    def __init__(
        self,
        config: RouterConfig,
        store: SessionStore | None = None,
        *,
        mode: OperatingMode | None = None,
        stats: RuntimeStats | None = None,
    ) -> None:
        self.config = config
        self.store = store if store is not None else SessionStore()
        if mode is None:
            mode = OperatingMode.ACTIVE if config.router_enabled else OperatingMode.OFF
        self.mode = mode
        self.stats = stats if stats is not None else RuntimeStats()

    @classmethod
    def from_options(
        cls, options: Mapping[str, object] | None, *, stats: RuntimeStats | None = None
    ) -> RouterBridge:
        mode = operating_mode(options)
        config = RouterConfig(router_enabled=mode is OperatingMode.ACTIVE)
        return cls(config, mode=mode, stats=stats)

    @property
    def enabled(self) -> bool:
        """True nur in Betriebsart ACTIVE: dann darf der Router Antworten bestimmen."""
        return self.mode is OperatingMode.ACTIVE and self.config.router_enabled is True

    @property
    def observing(self) -> bool:
        return self.mode is OperatingMode.OBSERVE

    def observe(self, *, text: object, language: str | None) -> None:
        """Betriebsart OBSERVE: Entscheidung nur berechnen und zaehlen.

        Keine Antwort, kein Hermes-Aufruf, kein Sitzungszustand (frischer Speicher,
        keine Conversation-ID). Wirft nie: Fehler werden nur gezaehlt.
        """
        if not self.observing:
            return
        try:
            decision = simulate(text, language)
        except Exception:  # noqa: BLE001 - Beobachtung darf den Aufrufer nie stoeren
            self.stats.record_observe_error()
            return
        self.stats.record_decision(OperatingMode.OBSERVE.value, decision.lane)

    async def async_handle(
        self,
        *,
        text: object,
        language: str | None,
        conversation_id: str | None,
        call_hermes: Callable[[], Awaitable[str | None]],
        hermes_errors: tuple[type[BaseException], ...],
    ) -> BridgeReply | None:
        """Bearbeitet einen Turn. None heisst: Router greift nicht ein.

        Fail-closed (R3.2): scheitert der Router selbst, bevor Hermes gefragt wurde,
        gibt es eine kurze neutrale Fehlerantwort statt des ungeprueften Hermes-Pfads.
        Fehler im Hermes-Aufruf werden wie bisher klassifiziert.
        """
        try:
            route_input = RouteInput(text, language or "", conversation_id)
            if not should_route(self.config, route_input):
                return None
            decision = route(route_input, self.store, self.config)
            self.stats.record_decision(OperatingMode.ACTIVE.value, decision.lane)
        except Exception:  # noqa: BLE001 - kein stiller Bypass des aktiven Routers
            with contextlib.suppress(Exception):
                self.stats.record_router_error()
            return BridgeReply(
                responses.LIVE_FAILURE_TEXT[FailureCode.UNKNOWN_FAILURE],
                True,
                False,
                ROUTER_FAILURE_DECISION,
            )
        if not decision.may_call_hermes:
            return BridgeReply(
                decision.response or responses.NOT_UNDERSTOOD, False, False, decision
            )

        started = time.monotonic()
        try:
            answer = await call_hermes()
        except hermes_errors as err:
            code = failure_from_exception(err)
            self.stats.record_hermes(code, time.monotonic() - started)
            self.store.record_failure(conversation_id, code, FailureSource.HERMES_COMPANION)
            return BridgeReply(responses.LIVE_FAILURE_TEXT[code], True, True, decision)
        if not isinstance(answer, str) or not answer.strip():
            code = FailureCode.UNKNOWN_FAILURE
            self.stats.record_hermes(code, time.monotonic() - started)
            self.store.record_failure(conversation_id, code, FailureSource.HERMES_COMPANION)
            return BridgeReply(responses.LIVE_FAILURE_TEXT[code], True, True, decision)
        self.stats.record_hermes(None, time.monotonic() - started)
        spoken, _replaced = normalize_chat_output(answer, narrative=is_narrative_request(text))
        return BridgeReply(spoken, False, True, decision)


def simulate(text: object, language: str | None) -> RouteDecision:
    """Reine Klassifikation fuer Beobachtung und Testanfrage.

    Frischer Sitzungsspeicher, keine Conversation-ID, Routing erzwungen: es entsteht
    kein Zustand, nichts wird gespeichert, nichts ausgefuehrt, Hermes nicht gerufen.
    """
    return route(
        RouteInput(text, language or ""), SessionStore(), RouterConfig(router_enabled=True)
    )
