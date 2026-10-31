"""Opt-in speech-correction core: explicit confirmation, no I/O or device actions.

Deliberately not wired into live conversation, options, or HA persistence yet.
Only confirmed word pairs may be exported; guesses and sessions stay ephemeral.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic

from .classify import Kind, classify

MAX_RULES = 128
MAX_SESSIONS = 64
MAX_UTTERANCE = 500
CONFIRMATION_TTL = 60.0
STORE_SCHEMA = 1

_PROTECTED = frozenset(
    "an aus ein auf zu on off ja nein stopp stop start schalt schalte schalten "
    "einschalten ausschalten aktivieren deaktivieren mach mache stelle stell "
    "öffne schließen licht lampe leuchte steckdose schalter heizung tür tor "
    "timer wecker alarm gerät status zustand kamera fenster rollladen "
    "pumpe aquarium staubsauger steuern bedienen".split()
)
_UNSAFE_IN_CHAT = frozenset(
    "schalt schalte schalten einschalten ausschalten aktivieren deaktivieren "
    "mach mache stell stelle öffne schließen stopp stop an aus on off "
    "status zustand gerät geräte".split()
)
_TOKEN = re.compile(r"(?<!\w)([^\W\d_]+)(?!\w)", re.UNICODE)


@dataclass(frozen=True)
class WordRule:
    heard: str
    intended: str


@dataclass(frozen=True)
class _Pending:
    rule: WordRule
    created_at: float


def _word(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    word = unicodedata.normalize("NFC", value.strip())
    if not 3 <= len(word) <= 40:
        return None
    if any(not unicodedata.category(char).startswith("L") for char in word):
        return None
    return None if word.casefold() in _PROTECTED else word


def _rule(heard: object, intended: object) -> WordRule | None:
    first, second = _word(heard), _word(intended)
    if first is None or second is None or first.casefold() == second.casefold():
        return None
    return WordRule(first, second)


def _safe_chat(text: str) -> bool:
    if not text or len(text) > MAX_UTTERANCE:
        return False
    if classify(text).kind not in (Kind.CHAT, Kind.KNOWLEDGE):
        return False
    words = {match.group(1).casefold() for match in _TOKEN.finditer(text)}
    return not bool(words & _UNSAFE_IN_CHAT)


class SpeechMemory:
    """Explicit-confirmation learner. External caller decides when to offer a proposal."""

    def __init__(self, *, clock=monotonic) -> None:
        self._clock = clock
        self._rules: dict[str, WordRule] = {}
        self._pending: dict[str, _Pending] = {}

    def propose(self, conversation_id: str | None, heard: str, intended: str) -> bool:
        """One short-lived candidate per session; does NOT write a learned rule."""
        if not isinstance(conversation_id, str) or not conversation_id or len(conversation_id) > 128:
            return False
        candidate = _rule(heard, intended)
        if candidate is None:
            return False
        self._expire()
        if conversation_id not in self._pending and len(self._pending) >= MAX_SESSIONS:
            return False
        self._pending[conversation_id] = _Pending(candidate, self._clock())
        return True

    def confirm(self, conversation_id: str | None, answer: str) -> bool:
        """Only an explicit 'yes' in the same unexpired session learns a rule."""
        self._expire()
        if not isinstance(conversation_id, str):
            return False
        pending = self._pending.pop(conversation_id, None)
        if pending is None or not isinstance(answer, str):
            return False
        if answer.strip().casefold().rstrip(".!?") not in {"ja", "ja bitte", "genau", "richtig"}:
            return False
        key = pending.rule.heard.casefold()
        if key not in self._rules and len(self._rules) >= MAX_RULES:
            return False
        self._rules[key] = pending.rule
        return True

    def apply(self, text: str, *, enabled: bool = False) -> str:
        """Whole-word replacements ONLY for harmless German chat, never commands."""
        if not enabled or not isinstance(text, str) or not self._rules or not _safe_chat(text):
            return text

        def corrected(match: re.Match[str]) -> str:
            rule = self._rules.get(match.group(1).casefold())
            return rule.intended if rule is not None else match.group(1)

        changed = _TOKEN.sub(corrected, text)
        return changed if _safe_chat(changed) else text

    def export_confirmed(self) -> dict[str, object]:
        """Persist only confirmed rules, never session IDs/transcripts/candidates."""
        return {
            "schema": STORE_SCHEMA,
            "rules": [
                {"heard": rule.heard, "intended": rule.intended}
                for rule in self._rules.values()
            ],
        }

    def import_confirmed(self, data: object) -> int:
        """Fail closed on invalid/future store format; reject malformed word pairs."""
        if not isinstance(data, Mapping) or data.get("schema") != STORE_SCHEMA:
            return 0
        rows = data.get("rules")
        if not isinstance(rows, list) or len(rows) > MAX_RULES:
            return 0
        rules: dict[str, WordRule] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            rule = _rule(row.get("heard"), row.get("intended"))
            if rule is not None:
                rules[rule.heard.casefold()] = rule
        self._rules = rules
        return len(rules)

    def delete(self, heard: str) -> bool:
        return isinstance(heard, str) and self._rules.pop(heard.casefold(), None) is not None

    def clear(self) -> None:
        self._rules.clear()
        self._pending.clear()

    def _expire(self) -> None:
        now = self._clock()
        self._pending = {
            key: pending
            for key, pending in self._pending.items()
            if 0 <= now - pending.created_at <= CONFIRMATION_TTL
        }
