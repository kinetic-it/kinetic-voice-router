"""Deutsche Standardantworten.

Kurz, ohne Erfolgsbehauptung, ohne Architektur- oder Debug-Erklaerung.
"""

from __future__ import annotations

from .model import ClarificationKind, FailureCode

NOT_EXECUTED = "Das konnte ich gerade nicht ausführen."
CAPABILITY_UNSURE = "Ob das geht, kann ich hier nicht sicher sagen."
CONFIRMATION_NOT_EXECUTABLE = "Ausführen kann ich das von hier aus nicht."
STATUS_NOT_AVAILABLE = "Den Gerätezustand kann ich von hier aus nicht abfragen."
CHAT_FOLLOWUP_UNCLEAR = "Ich habe dich nicht richtig verstanden. Kannst du das wiederholen?"
CHAT_FOLLOWUP_UNCLEAR_PREFIX = "Ich habe dich nicht richtig verstanden."

# Adaptive Speech Memory (only when learning is switched on, mode Active).
ASM_PROPOSE = "Soll ich mir merken, dass mit „{heard}“ „{intended}“ gemeint ist?"
ASM_PROPOSE_REPLACE = (
    "Bisher verstehe ich „{heard}“ als „{old}“. Soll ich mir stattdessen „{intended}“ merken?"
)
ASM_LEARNED = "Gemerkt: Mit „{heard}“ meinst du „{intended}“."
ASM_LEARNED_NO_AUTO = (
    "Gemerkt. Weil „{heard}“ ein gängiges Wort ist, ersetze ich es aber nicht automatisch."
)
ASM_NOT_LEARNED = "Alles klar, das merke ich mir nicht."
ASM_CANNOT_LEARN = "Das kann ich mir gerade nicht merken."
UNVERIFIED_SYSTEM_CLAIM = "Das kann ich gerade nicht sicher beantworten."
TOO_LONG_TO_SPEAK = (
    "Das ist zu ausführlich für eine gesprochene Antwort. Frag bitte gezielter nach."
)
NO_SAFE_REASON = "Dazu liegt mir kein sicherer Fehlergrund vor."
NOT_UNDERSTOOD = "Das habe ich nicht verstanden."
DECLINED = "Alles klar."
UNSUPPORTED_LANGUAGE = "Bitte sprich Deutsch mit mir."

FAILURE_TEXT: dict[FailureCode, str] = {
    FailureCode.ACTION_LIKE_UNHANDLED: (
        "Der Befehl kam bei mir an, und ich schalte selbst keine Geräte."
    ),
    FailureCode.STATUS_NOT_AVAILABLE: "Gerätezustände kann ich selbst nicht abfragen.",
    FailureCode.PROVIDER_TIMEOUT: "Die Antwort hat zu lange gedauert.",
    FailureCode.PROVIDER_UNAVAILABLE: "Meine Gesprächsfunktion war nicht verfügbar.",
    FailureCode.AUTH_FAILED: "Meine Gesprächsverbindung hat nicht funktioniert.",
    FailureCode.HA_UNREACHABLE: "Home Assistant war nicht erreichbar.",
    FailureCode.ENTITY_NOT_EXPOSED: "Darauf habe ich keinen Zugriff.",
    FailureCode.UNKNOWN_FAILURE: "Ich kann den Grund nicht sicher bestimmen.",
}

CLARIFICATION_TEXT: dict[ClarificationKind, str] = {
    ClarificationKind.QUESTION_OR_DEVICE: "Meinst du eine Frage oder ein Gerät?",
    ClarificationKind.ONE_THING_AT_A_TIME: "Bitte sag mir eins nach dem anderen.",
}

# Gesprochene Antwort im Moment eines belegten Gespraechsfehlers
# (Praesens).
# Keine Aussage ueber Home Assistant: ein Companion-Fehler ist kein HA-Fehler.
LIVE_FAILURE_TEXT: dict[FailureCode, str] = {
    FailureCode.PROVIDER_TIMEOUT: "Die Antwort dauert gerade zu lange.",
    FailureCode.PROVIDER_UNAVAILABLE: "Meine Gesprächsfunktion ist gerade nicht verfügbar.",
    FailureCode.AUTH_FAILED: "Meine Gesprächsverbindung funktioniert gerade nicht.",
    FailureCode.UNKNOWN_FAILURE: "Das hat gerade nicht geklappt.",
}
