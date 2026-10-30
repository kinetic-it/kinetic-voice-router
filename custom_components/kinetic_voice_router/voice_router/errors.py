"""Fehlerwahrheit: Provider-Fehler sicher klassifizieren, Modellausgaben pruefen.

Grundsatz: Ein Companion-/Provider-Fehler ist nie ein
Beleg fuer HA_UNREACHABLE oder ENTITY_NOT_EXPOSED. Eine freie Modellantwort ist nie
die Bestaetigung einer Geraeteaktion.
"""

from __future__ import annotations

import re

from . import responses
from .classify import is_device_term
from .model import FailureCode

# Fehlercodes des Hermes-Companions (API v1); hier nur als Zeichenketten gespiegelt, kein Import.
_COMPANION_CODE_MAP: dict[str, FailureCode] = {
    "unauthorized": FailureCode.AUTH_FAILED,
    "timeout": FailureCode.PROVIDER_TIMEOUT,
    "capability_unavailable": FailureCode.PROVIDER_UNAVAILABLE,
    "busy": FailureCode.PROVIDER_UNAVAILABLE,
    "provider_error": FailureCode.PROVIDER_UNAVAILABLE,
    "invalid_request": FailureCode.UNKNOWN_FAILURE,
    "internal_error": FailureCode.UNKNOWN_FAILURE,
}

_HTTP_STATUS_MAP: dict[int, FailureCode] = {
    401: FailureCode.AUTH_FAILED,
    403: FailureCode.AUTH_FAILED,
    502: FailureCode.PROVIDER_UNAVAILABLE,
    503: FailureCode.PROVIDER_UNAVAILABLE,
    504: FailureCode.PROVIDER_TIMEOUT,
}


def classify_companion_error(code: object = None, http_status: object = None) -> FailureCode:
    """Bildet einen Companion-Fehler auf eine sichere Klasse ab.

    Liefert nie HA_UNREACHABLE oder ENTITY_NOT_EXPOSED.
    """
    if isinstance(code, str) and code.strip().lower() in _COMPANION_CODE_MAP:
        return _COMPANION_CODE_MAP[code.strip().lower()]
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        return _HTTP_STATUS_MAP.get(http_status, FailureCode.UNKNOWN_FAILURE)
    return FailureCode.UNKNOWN_FAILURE


# Behauptungen, die ein Modell ohne Aktionspfad nicht machen darf.
_PARTICIPLES = (
    r"(eingeschaltet|ausgeschaltet|angeschaltet|abgeschaltet|angemacht|ausgemacht|geöffnet|"
    r"geschlossen|gestartet|gestoppt|aktiviert|deaktiviert|gedimmt|eingestellt|geschaltet|"
    r"gesperrt|entsperrt|gefüttert)"
)
_PARTICIPLES_OR_STATE = _PARTICIPLES[:-1] + r"|an|aus)"
_ACTION_CLAIMS = [
    # Ich-Form: "Ich habe das Licht eingeschaltet", "Hab ich gemacht"
    re.compile(r"\b(ich habe|habe ich|ich hab|hab ich)\b[^.!?]{0,60}\b" + _PARTICIPLES + r"\b"),
    # Vollzugsmeldung: "Das Licht ist jetzt an", "wurde soeben ausgeschaltet"
    re.compile(
        r"\b(ist|sind|wurde|wurden)\b (jetzt|nun|soeben|gerade|bereits) "
        + _PARTICIPLES_OR_STATE
        + r"\b"
    ),
    re.compile(r"^\s*(erledigt|gemacht|okay,? erledigt|alles klar,? erledigt)\b"),
    re.compile(r"\bich (schalte|öffne|schließe|starte|stoppe|aktiviere|deaktiviere|dimme)\b"),
]
# Index der Vollzugsmeldung in dritter Person; in einer erbetenen Geschichte ist
# "Das Licht ist jetzt an" Erzaehltext, keine Geraeteaktion (R3.2, #3).
_NARRATIVE_EXEMPT = 1
# Behaupteter Geraetecheck: "Ich habe nachgeschaut: Dein Warp-Antrieb ist aus" (R3.2, #2).
# Nur zusammen mit einer Zustandsaussage im selben Text, damit "Ich habe nachgeschaut,
# die Alpen sind 1200 km lang" erhalten bleibt.
_CHECK_CLAIM = re.compile(
    r"\b(ich habe|habe ich|ich hab|hab ich)\b[^.!?]{0,40}\b"
    r"(nachgeschaut|nachgesehen|geprüft|überprüft|gecheckt|kontrolliert)\b"
)
# Schalt-/Verbindungszustand am Satzende ("... ist aus."), nicht "ist zu weit".
_STATE_CLAIM = re.compile(
    r"\b(ist|sind|war|waren)\b[^.!?]{0,40}\b(an|aus|eingeschaltet|ausgeschaltet|"
    r"angeschaltet|abgeschaltet|online|offline)\s*([.!?]|$)"
)
# Unbelegte Systemaussagen ueber HA-Zugriff, -Berechtigung oder -Verbindung.
# Satzweise Pruefung: (Ich-Bezug ODER HA-Nennung) UND Mangel/Negation UND
# Zugriffsbegriff UND (Geraete-/Statusbezug ODER HA-Nennung). Damit bleiben
# Sachantworten wie "Ohne Verbindung zum Stromnetz leuchtet keine Lampe" erhalten.
_HA_NAME = re.compile(r"\b(home ?assistant|smart ?home|hausautomation|haussteuerung)\b")
_FIRST_PERSON = {"ich", "mir", "mich", "mein", "meine", "meinen", "meinem", "meiner"}
_LACK = {
    "kein",
    "keine",
    "keinen",
    "keiner",
    "nicht",
    "fehlt",
    "fehlen",
    "fehlende",
    "fehlenden",
    "ohne",
    "unterbrochen",
    "gestört",
    "offline",
    "ausgefallen",
    "down",
    "verweigert",
}
_ACCESS = (
    "zugriff",
    "zugreifen",
    "zugang",
    "berechtigung",
    "rechte",
    "anbindung",
    "verbindung",
    "verbunden",
    "erreichbar",
    "erreichen",
    "abfragen",
    "abrufen",
    "steuern",
    "schalten",
    "freigegeben",
    "freigabe",
    "exponiert",
    "exposed",
    "autorisiert",
    "verfügbar",
)
_STATUS_WORDS = ("status", "zustand", "zustände")
_EXPLICIT_EXPOSURE = re.compile(r"\b(nicht freigegeben|nicht exponiert|nicht exposed)\b")


# Eine ausdrueckliche Grenze des Gespraechskanals ist noch keine Aussage ueber
# HA-Berechtigungen oder Geraetezustaende (Issue #5 / R3.3). Nur diese beiden
# engen Formulierungen koennen einen Satz von der Systembehauptungspruefung
# ausnehmen, und nur, wenn der Rest des Satzes harmlos ist (siehe
# `_is_plain_channel_limit`). Alles andere, etwa "Home Assistant ist nicht
# erreichbar" oder "mir fehlen die Rechte", wird weiter streng geprueft.
_CHANNEL_LIMIT_EXPLANATIONS = (
    re.compile(r"\bich habe keinen direkten zugriff auf (?:die|den) schalter\b"),
    re.compile(
        r"\b(?:ich kann|kann ich) (?:die|den|das|deine|deinen|dein) "
        r"(?:[\wäöüß-]+\s+){0,2}[\wäöüß-]+ "
        r"nicht aus dem gespräch heraus (?:schalten|steuern)\b"
    ),
)
# "schalten"/"steuern" allein im Rest ("... du kannst sie selbst schalten") sind keine
# Berechtigungsaussage; alle anderen Zugriffs-/Rechtebegriffe sind es moeglicherweise.
_REMAINDER_NEUTRAL_ACCESS = ("steuern", "schalten")


def _is_plain_channel_limit(sentence: str) -> bool:
    """True, wenn der Satz nur eine erlaubte Kanalgrenze (plus Fuellwoerter) sagt.

    Die erlaubte Formulierung wird entfernt; der Rest darf weder einen Mangel
    (kein, nicht, fehlen, unterbrochen ...), noch einen Zugriffs-/Rechtebegriff
    (Berechtigung, Rechte, Verbindung, Freigabe ...), noch Home Assistant nennen.
    Sonst entscheidet die strenge Pruefung ueber den ganzen Satz.
    """
    rest = sentence
    matched = False
    for pattern in _CHANNEL_LIMIT_EXPLANATIONS:
        rest, count = pattern.subn(" ", rest)
        matched = matched or count > 0
    if not matched or _HA_NAME.search(rest):
        return False
    tokens = re.findall(r"[\wäöüß]+", rest)
    if _LACK & set(tokens):
        return False
    return not any(
        (t.startswith(_ACCESS) or t.endswith(_ACCESS))
        and not t.startswith(_REMAINDER_NEUTRAL_ACCESS)
        for t in tokens
    )


def _claims_ha_state(sentence: str) -> bool:
    if _EXPLICIT_EXPOSURE.search(sentence):
        return True
    if _is_plain_channel_limit(sentence):
        return False
    has_ha = bool(_HA_NAME.search(sentence))
    tokens = re.findall(r"[\wäöüß]+", sentence.replace("nicht nur", " "))
    first_person = bool(_FIRST_PERSON & set(tokens))
    if not (has_ha or first_person):
        return False
    lack = _LACK & set(tokens)
    if not first_person:
        # Sachaussage ueber HA ("funktioniert ohne Cloud") ist kein Ausfallbeleg.
        lack -= {"ohne"}
    if not lack:
        return False
    if not any(t.startswith(_ACCESS) or t.endswith(_ACCESS) for t in tokens):
        return False
    return has_ha or any(t.startswith(_STATUS_WORDS) or is_device_term(t) for t in tokens)


MAX_CHAT_SENTENCES = 2
MAX_CHAT_CHARS = 320
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Abkuerzungen und Listennummern am Stueckende ("z. B.", "d. h.", "ca.", "1."): kein Satzende.
_ABBREVIATION_END = re.compile(
    r"(?:^|\s)(?:\w|\d{1,2}|ca|bzw|usw|etc|vgl|nr|ggf|evtl|inkl|max|min|bspw|ugs|sog)\.$",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Teilt an Satzenden, nicht hinter Abkuerzungen oder Listennummern."""
    sentences: list[str] = []
    for piece in _SENTENCE_END.split(text):
        if sentences and _ABBREVIATION_END.search(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences


def normalize_chat_output(text: object, *, narrative: bool = False) -> tuple[str, bool]:
    """Prueft eine Hermes-Antwort der Spur CHAT.

    Rueckgabe: (sprechbarer Text, ersetzt?). Ersetzt wird bei leerer/ungueltiger
    Antwort, bei behaupteter Geraeteaktion, bei behauptetem Geraetecheck und bei
    unbelegter HA-Status-Behauptung. `narrative` (ausdruecklich erbetene Geschichte)
    nimmt nur die Vollzugsmeldung in dritter Person aus; Ich-Behauptungen bleiben
    gesperrt. Lange Antworten werden an Satzgrenzen gekuerzt, nie mitten im Satz.
    """
    if not isinstance(text, str) or not text.strip():
        return responses.FAILURE_TEXT[FailureCode.UNKNOWN_FAILURE], True
    lowered = text.lower()
    if any(
        p.search(lowered)
        for i, p in enumerate(_ACTION_CLAIMS)
        if not (narrative and i == _NARRATIVE_EXEMPT)
    ):
        return responses.NOT_EXECUTED, True
    if _CHECK_CLAIM.search(lowered) and _STATE_CLAIM.search(lowered):
        return responses.UNVERIFIED_SYSTEM_CLAIM, True
    normalized = lowered.replace("-", " ")
    if any(_claims_ha_state(sentence) for sentence in re.split(r"[.!?;:]+", normalized)):
        return responses.UNVERIFIED_SYSTEM_CLAIM, True
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= MAX_CHAT_CHARS:
        return cleaned, False
    sentences = _split_sentences(cleaned)
    kept: list[str] = []
    for sentence in sentences[:MAX_CHAT_SENTENCES]:
        if kept and len(" ".join(kept + [sentence])) > MAX_CHAT_CHARS:
            break
        kept.append(sentence)
    result = " ".join(kept)
    if len(result) > MAX_CHAT_CHARS or not re.search(r"[.!?]$", result):
        # Kein sauberes Satzende innerhalb der Grenze: nicht mitten im Satz abschneiden und
        # nicht mit einem falschen Fehlergrund antworten, sondern ehrlich sagen warum.
        return responses.TOO_LONG_TO_SPEAK, True
    return result, True
