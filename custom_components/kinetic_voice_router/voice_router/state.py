"""Kurzlebiger In-Memory-Sitzungszustand.

Gespeichert wird je Conversation-ID hoechstens:
- die letzte bereinigte FailureSummary (Code, Quelle, monotone Zeit),
- die Art einer offenen Router-Rueckfrage,
- ein kurzes Zeitfenster fuer eine offene Chat-Rueckfrage (ohne Wortlaut).

Kein Wortlaut, keine Entitaet, keine Persistenz ueber Neustarts.
Ohne Conversation-ID wird nichts gespeichert.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .model import HA_ONLY_CODES, ClarificationKind, FailureCode, FailureSource, FailureSummary

DEFAULT_TTL_SECONDS = 120.0
CHAT_FOLLOWUP_TTL_SECONDS = 60.0
MAX_SESSIONS = 64


@dataclass
class _Entry:
    failure: FailureSummary | None = None
    clarification: ClarificationKind | None = None
    clarification_at: float = 0.0
    chat_followup_at: float | None = None


class SessionStore:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max = max_sessions
        self._entries: dict[str, _Entry] = {}

    def _entry(self, conversation_id: str) -> _Entry:
        entry = self._entries.get(conversation_id)
        if entry is None:
            if len(self._entries) >= self._max:
                # aeltesten Eintrag verwerfen (dict behaelt Einfuegereihenfolge)
                self._entries.pop(next(iter(self._entries)))
            entry = _Entry()
            self._entries[conversation_id] = entry
        return entry

    def _fresh(self, at: float) -> bool:
        return (self._clock() - at) <= self._ttl

    def record_failure(
        self, conversation_id: str | None, code: FailureCode, source: FailureSource
    ) -> bool:
        """Speichert einen verifizierten Fehler. Ohne sichere Bindung: verwerfen.

        HA_UNREACHABLE und ENTITY_NOT_EXPOSED nur mit Quelle HA.
        """
        if not _valid_id(conversation_id):
            return False
        if code in HA_ONLY_CODES and source is not FailureSource.HA:
            return False
        self._entry(conversation_id).failure = FailureSummary(code, source, self._clock())
        return True

    def last_failure(self, conversation_id: str | None) -> FailureSummary | None:
        if not _valid_id(conversation_id):
            return None
        entry = self._entries.get(conversation_id)
        if entry is None or entry.failure is None:
            return None
        if not self._fresh(entry.failure.occurred_at_monotonic):
            entry.failure = None
            return None
        return entry.failure

    def set_clarification(self, conversation_id: str | None, kind: ClarificationKind) -> bool:
        if not _valid_id(conversation_id):
            return False
        entry = self._entry(conversation_id)
        entry.clarification = kind
        entry.clarification_at = self._clock()
        return True

    def pop_clarification(self, conversation_id: str | None) -> ClarificationKind | None:
        """Liefert und entfernt eine offene, noch gueltige Rueckfrage."""
        if not _valid_id(conversation_id):
            return None
        entry = self._entries.get(conversation_id)
        if entry is None or entry.clarification is None:
            return None
        kind = entry.clarification
        entry.clarification = None
        return kind if self._fresh(entry.clarification_at) else None

    def set_chat_followup(self, conversation_id: str | None) -> bool:
        """Arm a short, single-use chat follow-up without storing any spoken text."""
        if not _valid_id(conversation_id):
            return False
        self._entry(conversation_id).chat_followup_at = self._clock()
        return True

    def pop_chat_followup(self, conversation_id: str | None) -> bool:
        """Consume the next follow-up once; never revive an expired question."""
        if not _valid_id(conversation_id):
            return False
        entry = self._entries.get(conversation_id)
        if entry is None:
            return False
        at = entry.chat_followup_at
        entry.chat_followup_at = None
        return at is not None and 0 <= self._clock() - at <= min(
            self._ttl, CHAT_FOLLOWUP_TTL_SECONDS
        )

    def clear_chat_followup(self, conversation_id: str | None) -> None:
        if _valid_id(conversation_id) and conversation_id in self._entries:
            self._entries[conversation_id].chat_followup_at = None

    def clear_clarification(self, conversation_id: str | None) -> None:
        if _valid_id(conversation_id) and conversation_id in self._entries:
            self._entries[conversation_id].clarification = None


def _valid_id(conversation_id: object) -> bool:
    return isinstance(conversation_id, str) and conversation_id.strip() != ""
