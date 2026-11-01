"""Adaptive Speech Memory (ASM): confirmed word corrections, pure Python, no I/O.

What it does
- Holds a bounded lexicon of confirmed pairs `heard -> intended` (e.g. "Mulahn" ->
  "Mulan"). Pairs only exist after an explicit confirmation in a conversation or a
  manual entry in the Home Assistant options.
- Recognises correction statements ("Nein, ich meinte Mulan", "nicht Mulahn, sondern
  Mulan") and finds the misheard word in the previous user turn. If that word is not
  reliably identifiable, it returns nothing; it never guesses.
- Applies auto-correctable pairs to harmless conversation text only.

What it never does
- No device, room, control, status or confirmation vocabulary is learned or replaced.
- No replacement in anything the router does not classify as conversation/knowledge.
- No single letters or very short fragments ("T.") are learned or resolved.
- No storage of sentences, conversation IDs, audio or identities (the HA side persists
  only the pairs returned by `export_data`).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from .classify import Kind, classify, is_device_term, normalize

SCHEMA_VERSION = 1
MAX_ENTRIES = 200
MAX_PHRASE_CHARS = 40
MAX_PHRASE_WORDS = 3
MIN_HEARD_CHARS = 3
MAX_TEXT_CHARS = 500
SIMILARITY_THRESHOLD = 0.6


class Category(StrEnum):
    """How a pair may be used. Only the first three are applied automatically."""

    NAME = "name"  # proper name ("Mulan")
    TERM = "term"  # unusual technical term
    STT = "stt"  # frequent speech-to-text misspelling
    AMBIGUOUS = "ambiguous"  # stored for reference, never applied automatically


AUTO_APPLY = frozenset({Category.NAME, Category.TERM, Category.STT})


class Source(StrEnum):
    DIALOGUE = "dialogue"  # confirmed with "yes" in a conversation
    MANUAL = "manual"  # entered by an administrator in the options


class Rejection(StrEnum):
    """Why a pair cannot be stored (shown as an error in the options)."""

    INVALID = "invalid"  # empty, too long, digits, symbols, too many words
    TOO_SHORT = "too_short"  # single letters / fragments such as "T"
    SAME = "same"  # heard == intended
    PROTECTED = "protected"  # device, room, control, status or confirmation word
    CONFLICT = "conflict"  # heard already maps to another word
    CHAIN = "chain"  # would create A->B->C or A<->B
    FULL = "full"  # lexicon limit reached
    UNKNOWN_ENTRY = "unknown_entry"
    READ_ONLY = "read_only"  # stored lexicon could not be read; nothing is written


# Control, status and confirmation vocabulary: never learned, never rewritten.
_PROTECTED_WORDS = frozenset(
    (
        "an aus ein auf zu on off ja nein nö ne jo jap stopp stop start halt "
        "genau richtig okay ok bitte danke mach mache machen tu tue "
        "schalt schalte schalten einschalten ausschalten anschalten abschalten "
        "anmachen ausmachen aktivieren deaktivieren aktiviere deaktiviere "
        "öffne öffnen schließe schließen sperre sperren entsperre entsperren "
        "dimme dimmen stell stelle stellen dreh drehe drehen starte starten stoppe stoppen "
        "hoch runter heller dunkler lauter leiser wärmer kälter "
        "status zustand zustände gerät geräte entität alarm notfall hilfe "
        "licht lampe leuchte steckdose schalter heizung thermostat fenster tür tor "
        "rollladen rolladen jalousie garage kamera schloss türschloss "
        "timer wecker musik lautsprecher "
        # rooms: never part of a learned pair (room names steer devices)
        "wohnzimmer küche bad badezimmer schlafzimmer kinderzimmer flur diele keller "
        "dachboden büro arbeitszimmer esszimmer gästezimmer garten balkon terrasse "
        "eingang treppe treppenhaus waschküche"
    ).split()
)
# Everyday words: may be stored by an administrator, but only as AMBIGUOUS
# (never replaced automatically) because they occur in normal sentences.
_COMMON_WORDS = frozenset(
    (
        "der die das den dem des ein eine einen einem einer und oder aber nicht "
        "ich du er sie es wir ihr mir mich dir dich uns euch mein dein sein "
        "ist sind war bin hat habe haben wird werden kann können soll will "
        "was wer wie wo wann warum wieso weshalb welche welcher welches "
        "mit von vom zu zum zur für über unter vor nach bei aus auf in im "
        "heute morgen gestern jetzt hier dort da noch schon mal gut neu alt "
        "tee kaffee wasser milch brot haus auto zeit tag nacht woche jahr "
        "mann frau kind name wort sache ding bild film buch lied spiel "
        "meer see berg wald stadt land welt sonne mond stern"
    ).split()
)

_WORD = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
_CONFIRM = frozenset(
    {
        "ja",
        "ja bitte",
        "ja gerne",
        "ja gern",
        "genau",
        "richtig",
        "merk dir das",
        "merke dir das",
        "ja merk dir das",
        "ja merke dir das",
        "ja bitte merken",
        "bitte merken",
    }
)
_DECLINE = frozenset(
    {
        "nein",
        "nö",
        "ne",
        "nein danke",
        "lieber nicht",
        "nicht merken",
        "nein nicht merken",
        "vergiss es",
        "abbrechen",
    }
)

# Correction statements. Group "intended" (and optionally "heard") are 1-3 words.
_PHRASE = r"[^\W\d_]+(?:[-'][^\W\d_]+)*(?: [^\W\d_]+(?:[-'][^\W\d_]+)*){0,2}"
_CORRECTION_PATTERNS = (
    # "nicht Mulahn, sondern Mulan"
    re.compile(rf"^(?:nein )?nicht (?P<heard>{_PHRASE}) sondern (?P<intended>{_PHRASE})$"),
    # "Mulan, nicht Mulahn"
    re.compile(rf"^(?:nein )?(?P<intended>{_PHRASE}) nicht (?P<heard>{_PHRASE})$"),
    # "Nein, ich meinte Mulan" / "ich meine Mulan" / "gemeint war Mulan" / "ich sagte Mulan"
    re.compile(
        rf"^(?:nein )?(?:ich meinte|ich meine|gemeint war|gemeint ist|ich sagte|ich wollte) "
        rf"(?P<intended>{_PHRASE})$"
    ),
    # "Ich habe Mulan gesagt"
    re.compile(rf"^(?:nein )?ich (?:habe|hab) (?P<intended>{_PHRASE}) gesagt$"),
)


@dataclass(frozen=True)
class Entry:
    heard: str
    intended: str
    category: Category
    source: Source
    confirmed_on: str  # ISO date (YYYY-MM-DD), no time of day

    @property
    def key(self) -> str:
        return _key(self.heard)

    @property
    def auto_apply(self) -> bool:
        return self.category in AUTO_APPLY


@dataclass(frozen=True)
class Correction:
    """A correction statement with the misheard word reliably identified."""

    heard: str
    intended: str


def _key(phrase: str) -> str:
    return " ".join(phrase.casefold().split())


def clean_phrase(value: object) -> str | None:
    """NFC-normalised 1-3 letter words (hyphen/apostrophe inside words allowed)."""
    if not isinstance(value, str):
        return None
    phrase = " ".join(unicodedata.normalize("NFKC", value).split())
    phrase = "".join(ch for ch in phrase if unicodedata.category(ch) != "Cf")
    if not phrase or len(phrase) > MAX_PHRASE_CHARS:
        return None
    words = phrase.split(" ")
    if len(words) > MAX_PHRASE_WORDS or not all(_WORD.fullmatch(word) for word in words):
        return None
    return phrase


def _protected(phrase: str) -> bool:
    for word in _key(phrase).split():
        if word in _PROTECTED_WORDS or is_device_term(word):
            return True
    return False


def is_common(phrase: str) -> bool:
    return any(word in _COMMON_WORDS for word in _key(phrase).split())


def check_pair(heard: object, intended: object) -> tuple[str, str] | Rejection:
    """Validate a pair independent of the lexicon. Returns cleaned phrases or a reason."""
    clean_heard, clean_intended = clean_phrase(heard), clean_phrase(intended)
    if clean_heard is None or clean_intended is None:
        if isinstance(heard, str) and 0 < len(heard.strip(" .,!?")) < MIN_HEARD_CHARS:
            return Rejection.TOO_SHORT
        return Rejection.INVALID
    if len(clean_heard.replace(" ", "")) < MIN_HEARD_CHARS or len(clean_intended) < 2:
        return Rejection.TOO_SHORT
    if _key(clean_heard) == _key(clean_intended):
        return Rejection.SAME
    if _protected(clean_heard) or _protected(clean_intended):
        return Rejection.PROTECTED
    return clean_heard, clean_intended


def suggested_category(heard: str) -> Category:
    """Dialogue-learned pairs: common words become AMBIGUOUS, everything else STT."""
    return Category.AMBIGUOUS if is_common(heard) else Category.STT


def is_confirmation(text: object) -> bool:
    return isinstance(text, str) and normalize(text) in _CONFIRM


def is_decline(text: object) -> bool:
    return isinstance(text, str) and normalize(text) in _DECLINE


def _harmless(text: str) -> bool:
    """Only conversation/knowledge sentences without control vocabulary."""
    if not text or len(text) > MAX_TEXT_CHARS:
        return False
    normalized = normalize(text)
    if not normalized:
        return False
    if classify(normalized).kind not in (Kind.CHAT, Kind.KNOWLEDGE):
        return False
    return not any(word in _PROTECTED_WORDS or is_device_term(word) for word in normalized.split())


def parse_correction(current: object, previous_user_text: object) -> Correction | None:
    """Recognise a correction and identify the misheard phrase in the previous turn.

    Returns None unless BOTH the intended phrase and the misheard phrase are reliable:
    the misheard phrase must occur as whole words in the previous user turn, and when
    it is not named explicitly there must be exactly one similar candidate.
    """
    if not isinstance(current, str) or not isinstance(previous_user_text, str):
        return None
    if not _harmless(previous_user_text):
        return None
    sentence = normalize(current)
    if not sentence or len(sentence) > 120:
        return None
    heard_text: str | None = None
    intended_text: str | None = None
    for pattern in _CORRECTION_PATTERNS:
        match = pattern.fullmatch(sentence)
        if match is None:
            continue
        groups = match.groupdict()
        intended_text = groups.get("intended")
        heard_text = groups.get("heard")
        break
    if not intended_text:
        return None
    intended = _original_case(current, intended_text)
    previous_words = _WORD.findall(previous_user_text)
    if heard_text is not None:
        heard = _find_phrase(previous_words, heard_text)
        if heard is None:
            return None  # the user named a word that was not in the previous turn
    else:
        heard = _single_similar(previous_words, intended_text)
        if heard is None:
            return None  # none or several candidates: do not guess
    checked = check_pair(heard, intended)
    if isinstance(checked, Rejection):
        return None
    return Correction(*checked)


def _original_case(current: str, normalized_phrase: str) -> str:
    """Recover the user's spelling (normalize() lowercases)."""
    words = _WORD.findall(current)
    wanted = normalized_phrase.split()
    for i in range(len(words) - len(wanted) + 1):
        if [w.casefold() for w in words[i : i + len(wanted)]] == wanted:
            return " ".join(words[i : i + len(wanted)])
    return normalized_phrase


def _find_phrase(words: list[str], phrase: str) -> str | None:
    wanted = phrase.split()
    for i in range(len(words) - len(wanted) + 1):
        if [w.casefold() for w in words[i : i + len(wanted)]] == wanted:
            return " ".join(words[i : i + len(wanted)])
    return None


def _single_similar(words: list[str], intended: str) -> str | None:
    """Exactly one previous word (or short span) similar to the intended phrase.

    Spans overlapping the best match are variants of the same position and do not
    count as rivals; any similar span elsewhere in the sentence makes it ambiguous.
    """
    target = _key(intended)
    if target in (w.casefold() for w in words):
        return None  # the intended word was already there: nothing was misheard
    size = len(target.split())
    scored: list[tuple[float, int, int]] = []
    for n in sorted({size, max(1, size - 1), size + 1}):
        if n > MAX_PHRASE_WORDS:
            continue
        for i in range(len(words) - n + 1):
            span = " ".join(words[i : i + n])
            if len(span.replace(" ", "")) < MIN_HEARD_CHARS or _protected(span):
                continue
            score = _similarity(_key(span), target)
            if score >= SIMILARITY_THRESHOLD:
                scored.append((score, i, n))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[2]))
    _, start, length = scored[0]
    best = range(start, start + length)
    rivals = [s for s in scored[1:] if not set(range(s[1], s[1] + s[2])) & set(best)]
    if rivals:
        return None
    return " ".join(words[start : start + length])


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()


class SpeechMemory:
    """The confirmed lexicon. Persistence is done by the caller via export/import."""

    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        self._entries: dict[str, Entry] = {}
        for entry in entries:
            self._entries[entry.key] = entry

    # --- read -------------------------------------------------------------------------

    def entries(self) -> list[Entry]:
        return sorted(self._entries.values(), key=lambda e: e.heard.casefold())

    def get(self, heard: object) -> Entry | None:
        return self._entries.get(_key(heard)) if isinstance(heard, str) else None

    def __len__(self) -> int:
        return len(self._entries)

    # --- write (each returns the stored entry or a Rejection) --------------------------

    def add(
        self,
        heard: object,
        intended: object,
        *,
        category: Category,
        source: Source,
        today: str,
        replace_existing: bool = False,
    ) -> Entry | Rejection:
        checked = check_pair(heard, intended)
        if isinstance(checked, Rejection):
            return checked
        clean_heard, clean_intended = checked
        if is_common(clean_heard) and category in AUTO_APPLY:
            category = Category.AMBIGUOUS
        key = _key(clean_heard)
        existing = self._entries.get(key)
        if existing is not None and not replace_existing:
            if _key(existing.intended) == _key(clean_intended):
                return existing  # duplicate: nothing to do
            return Rejection.CONFLICT
        # no chains or cycles: the target must not itself be a misheard phrase,
        # and the misheard phrase must not be anybody's target
        if _key(clean_intended) in self._entries and _key(clean_intended) != key:
            return Rejection.CHAIN
        if any(_key(entry.intended) == key for k, entry in self._entries.items() if k != key):
            return Rejection.CHAIN
        if existing is None and len(self._entries) >= MAX_ENTRIES:
            return Rejection.FULL
        entry = Entry(clean_heard, clean_intended, category, source, today)
        self._entries[key] = entry
        return entry

    def update(
        self, heard: object, intended: object, *, category: Category, today: str
    ) -> Entry | Rejection:
        existing = self.get(heard)
        if existing is None:
            return Rejection.UNKNOWN_ENTRY
        result = self.add(
            existing.heard,
            intended,
            category=category,
            source=Source.MANUAL,
            today=today,
            replace_existing=True,
        )
        if isinstance(result, Rejection):
            return result
        return result

    def delete(self, heard: object) -> bool:
        return isinstance(heard, str) and self._entries.pop(_key(heard), None) is not None

    def clear(self) -> None:
        self._entries.clear()

    def set_category(self, heard: str, category: Category) -> Entry | None:
        entry = self.get(heard)
        if entry is None:
            return None
        updated = replace(entry, category=category)
        self._entries[entry.key] = updated
        return updated

    # --- use ----------------------------------------------------------------------------

    def apply(self, text: object) -> str | None:
        """Corrected text, or None if nothing may or needs to be changed.

        Only harmless conversation is rewritten, only whole words/phrases, only with
        auto-correctable entries, in a single pass (no chains), and the result must
        still be harmless conversation.
        """
        if not isinstance(text, str) or not self._entries or not _harmless(text):
            return None
        usable = sorted(
            (e for e in self._entries.values() if e.auto_apply),
            key=lambda e: -len(e.heard),
        )
        if not usable:
            return None
        pattern = re.compile(
            r"(?<![^\W\d_])(" + "|".join(re.escape(e.heard) for e in usable) + r")(?![^\W\d_])",
            re.IGNORECASE,
        )
        lookup = {e.key: e.intended for e in usable}
        changed = pattern.sub(lambda m: lookup.get(_key(m.group(1)), m.group(1)), text)
        if changed == text or not _harmless(changed):
            return None
        return changed

    # --- persistence contract ----------------------------------------------------------

    def export_data(self) -> dict[str, object]:
        return {
            "entries": [
                {
                    "heard": e.heard,
                    "intended": e.intended,
                    "category": e.category.value,
                    "source": e.source.value,
                    "confirmed_on": e.confirmed_on,
                }
                for e in self.entries()
            ]
        }


class LoadError(ValueError):
    """Stored lexicon is unusable; the caller must not overwrite it silently."""


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_entries(data: object) -> list[Entry]:
    """Strict reader for the stored payload. Any invalid row makes the whole load fail.

    Failing closed lets the integration keep the stored file untouched and show the
    problem instead of silently dropping (and later overwriting) entries.
    """
    if data is None:
        return []
    if not isinstance(data, Mapping) or not isinstance(data.get("entries"), list):
        raise LoadError("no entry list")
    rows = data["entries"]
    if len(rows) > MAX_ENTRIES:
        raise LoadError("too many entries")
    memory = SpeechMemory()
    for row in rows:
        if not isinstance(row, Mapping):
            raise LoadError("entry is not an object")
        try:
            category = Category(row.get("category"))
            source = Source(row.get("source"))
        except ValueError as err:
            raise LoadError("unknown category or source") from err
        confirmed_on = row.get("confirmed_on")
        if not isinstance(confirmed_on, str) or not _DATE.match(confirmed_on):
            raise LoadError("invalid date")
        result = memory.add(
            row.get("heard"),
            row.get("intended"),
            category=category,
            source=source,
            today=confirmed_on,
        )
        if isinstance(result, Rejection):
            raise LoadError(f"invalid entry ({result.value})")
    return memory.entries()
