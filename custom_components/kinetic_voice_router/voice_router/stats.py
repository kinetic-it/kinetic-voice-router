"""Datensparsame Laufzeitstatistik (R3, P2).

Nur ganzzahlige Zaehler mit festen Schluesseln: Entscheidungen je Betriebsart und
Spur, Ergebnis der Hermes-Aufrufe im aktiven Modus und deren Dauer in groben
Klassen. Kein Wortlaut, keine Conversation-ID, keine Zeitstempel einzelner
Anfragen. Prozess-Lebenszeitwerte: nach einem HA-Neustart beginnen sie bei 0,
`reset()` setzt sie auf 0. Keine Persistenz.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .model import FailureCode, Lane

# Obergrenzen (Sekunden) der Dauerklassen fuer Hermes-Antworten.
LATENCY_BUCKETS: tuple[tuple[str, float], ...] = (
    ("under_2s", 2.0),
    ("under_5s", 5.0),
    ("under_15s", 15.0),
    ("over_15s", float("inf")),
)
_MODES = ("observe", "active")
# Nur Klassen, die ein Hermes-Aufruf tatsaechlich liefern kann (nie HA-Fehler).
_HERMES_FAILURES = (
    FailureCode.PROVIDER_TIMEOUT,
    FailureCode.PROVIDER_UNAVAILABLE,
    FailureCode.AUTH_FAILED,
    FailureCode.UNKNOWN_FAILURE,
)


class RuntimeStats:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.decisions = {mode: {lane.value: 0 for lane in Lane} for mode in _MODES}
        self.hermes = {"ok": 0, **{code.value: 0 for code in _HERMES_FAILURES}}
        self.latency = {name: 0 for name, _ in LATENCY_BUCKETS}
        self.observe_errors = 0
        self.router_errors = 0
        self._since = self._clock()

    def record_decision(self, mode: str, lane: Lane) -> None:
        if mode in self.decisions:
            self.decisions[mode][lane.value] += 1

    def record_hermes(self, outcome: FailureCode | None, seconds: float) -> None:
        key = "ok" if outcome is None else outcome.value
        if key in self.hermes:
            self.hermes[key] += 1
        for name, upper in LATENCY_BUCKETS:
            if seconds < upper:
                self.latency[name] += 1
                break

    def record_observe_error(self) -> None:
        self.observe_errors += 1

    def record_router_error(self) -> None:
        """Interner Routerfehler im aktiven Modus (fail-closed beantwortet)."""
        self.router_errors += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "scope": "process_lifetime",
            "seconds_since_reset": int(max(0.0, self._clock() - self._since)),
            "decisions": {mode: dict(counts) for mode, counts in self.decisions.items()},
            "hermes_results": dict(self.hermes),
            "hermes_latency": dict(self.latency),
            "observe_errors": self.observe_errors,
            "router_errors": self.router_errors,
        }
