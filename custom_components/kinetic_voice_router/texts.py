"""German/English texts for values shown in options-flow placeholders.

Home Assistant translates the static strings itself (strings.json); placeholder
values are inserted verbatim, so they are localised here.
"""

from __future__ import annotations

from typing import Any

from .voice_router import ReasonCode

REASONS: dict[str, dict[ReasonCode, str]] = {
    "de": {
        ReasonCode.KNOWLEDGE_QUESTION: "Wissensfrage – geht an Hermes.",
        ReasonCode.CONVERSATION: "Gespräch – geht an Hermes.",
        ReasonCode.ACTION_LIKE_WITHOUT_EXECUTION: (
            "Steuerbefehl, den Home Assistant nicht lokal erledigt hat – der Router schaltet nicht."
        ),
        ReasonCode.CAPABILITY_QUESTION: "Frage nach einer Fähigkeit – keine Zusage.",
        ReasonCode.CONFIRMATION_WITHOUT_EXECUTION_PATH: "Bestätigung – führt nichts aus.",
        ReasonCode.STATUS_QUERY_WITHOUT_VERIFIED_ACCESS: (
            "Statusanfrage zu einem Gerät – der Router kennt keinen Gerätezustand."
        ),
        ReasonCode.EXPLICIT_DEBUG_VERIFIED: "Nachfrage zum letzten Fehler – belegter Grund.",
        ReasonCode.EXPLICIT_DEBUG_NO_EVIDENCE: (
            "Nachfrage zum letzten Fehler – im Test gibt es keinen belegten Fehler."
        ),
        ReasonCode.EMPTY_INPUT: "Leere Eingabe.",
        ReasonCode.INPUT_TOO_LONG: "Eingabe zu lang.",
        ReasonCode.INVALID_INPUT: "Ungültige Eingabe.",
        ReasonCode.UNSUPPORTED_LANGUAGE: "Sprache nicht unterstützt.",
        ReasonCode.AMBIGUOUS_FRAGMENT: "Mehrdeutig – kurze Rückfrage.",
        ReasonCode.AMBIGUOUS_MIXED: "Frage und Befehl gemischt – kurze Rückfrage.",
        ReasonCode.BARE_CONFIRMATION: "„Ja“/„Nein“ ohne offene Rückfrage.",
        ReasonCode.CLARIFICATION_DECLINED: "Rückfrage abgelehnt.",
        ReasonCode.UNCLASSIFIED: "Nicht zuzuordnen.",
        ReasonCode.LOCAL_ALREADY_HANDLED: "Von Home Assistant lokal erledigt.",
    },
    "en": {
        ReasonCode.KNOWLEDGE_QUESTION: "Knowledge question – goes to Hermes.",
        ReasonCode.CONVERSATION: "Conversation – goes to Hermes.",
        ReasonCode.ACTION_LIKE_WITHOUT_EXECUTION: (
            "Device command Home Assistant did not handle locally – the router does not switch."
        ),
        ReasonCode.CAPABILITY_QUESTION: "Capability question – no promise made.",
        ReasonCode.CONFIRMATION_WITHOUT_EXECUTION_PATH: "Confirmation – executes nothing.",
        ReasonCode.STATUS_QUERY_WITHOUT_VERIFIED_ACCESS: (
            "Device status question – the router knows no device state."
        ),
        ReasonCode.EXPLICIT_DEBUG_VERIFIED: "Question about the last error – verified reason.",
        ReasonCode.EXPLICIT_DEBUG_NO_EVIDENCE: (
            "Question about the last error – the test has no recorded error."
        ),
        ReasonCode.EMPTY_INPUT: "Empty input.",
        ReasonCode.INPUT_TOO_LONG: "Input too long.",
        ReasonCode.INVALID_INPUT: "Invalid input.",
        ReasonCode.UNSUPPORTED_LANGUAGE: "Language not supported.",
        ReasonCode.AMBIGUOUS_FRAGMENT: "Ambiguous – short follow-up question.",
        ReasonCode.AMBIGUOUS_MIXED: "Question and command mixed – short follow-up question.",
        ReasonCode.BARE_CONFIRMATION: "Yes/no without an open follow-up question.",
        ReasonCode.CLARIFICATION_DECLINED: "Follow-up question declined.",
        ReasonCode.UNCLASSIFIED: "Could not be classified.",
        ReasonCode.LOCAL_ALREADY_HANDLED: "Handled locally by Home Assistant.",
    },
}

FORWARD_TO_HERMES = {
    "de": "(würde an Hermes weitergegeben – im Test kein Aufruf)",
    "en": "(would be forwarded to Hermes – not called in the test)",
}

MODE_LABELS = {
    "de": {"off": "Aus", "observe": "Beobachten", "active": "Aktiv"},
    "en": {"off": "Off", "observe": "Observe", "active": "Active"},
}


def language(hass: Any) -> str:
    value = str(getattr(getattr(hass, "config", None), "language", "en") or "en")
    return "de" if value.lower().startswith("de") else "en"


ROUTE_LABELS = {
    "de": {
        "CHAT": "Gespräch/Wissen",
        "CONTROL_FALLBACK": "Geräte- oder Statusanfrage (ohne Ausführung)",
        "EXPLAIN_LAST": "Nachfrage zum letzten Fehler",
        "UNKNOWN": "Unklar – kurze Rückfrage oder Hinweis",
    },
    "en": {
        "CHAT": "Conversation/knowledge",
        "CONTROL_FALLBACK": "Device or status request (not executed)",
        "EXPLAIN_LAST": "Question about the last error",
        "UNKNOWN": "Unclear – short follow-up or hint",
    },
}

HERMES_RESULT_LABELS = {
    "de": {
        "ok": "erfolgreich",
        "PROVIDER_TIMEOUT": "Zeitüberschreitung",
        "PROVIDER_UNAVAILABLE": "nicht verfügbar",
        "AUTH_FAILED": "Anmeldung abgelehnt",
        "UNKNOWN_FAILURE": "sonstiger Fehler",
    },
    "en": {
        "ok": "successful",
        "PROVIDER_TIMEOUT": "timeout",
        "PROVIDER_UNAVAILABLE": "unavailable",
        "AUTH_FAILED": "authentication rejected",
        "UNKNOWN_FAILURE": "other error",
    },
}

LATENCY_LABELS = {
    "de": {
        "under_2s": "unter 2 s",
        "under_5s": "2–5 s",
        "under_15s": "5–15 s",
        "over_15s": "über 15 s",
    },
    "en": {
        "under_2s": "under 2 s",
        "under_5s": "2–5 s",
        "under_15s": "5–15 s",
        "over_15s": "over 15 s",
    },
}

_SUMMARY = {
    "de": {
        "off_note": "Router ist aus – es werden keine Routerentscheidungen erfasst.",
        "empty": "Noch keine erfassten Anfragen.",
        "observe": (
            "**Beobachten:** {total} erfasste Anfragen\n"
            "- würden an Hermes gehen: {chat}\n"
            "- Router hätte geantwortet: {router}"
        ),
        "active": (
            "**Aktiv:** {total} erfasste Anfragen\n"
            "- an Hermes weitergegeben: {chat}\n"
            "- vom Router beantwortet: {router}\n"
            "- Hermes-Fehler: {errors}"
        ),
        "observe_errors": "Beobachtungsfehler: {count}",
        "router_errors": "Interne Routerfehler (neutral beantwortet, nicht an Hermes): {count}",
        "footer": "Seit {minutes} min (HA-Start oder Zurücksetzen). Testanfragen zählen nicht.",
    },
    "en": {
        "off_note": "Router is off – no router decisions are being recorded.",
        "empty": "No recorded requests yet.",
        "observe": (
            "**Observe:** {total} recorded requests\n"
            "- would go to Hermes: {chat}\n"
            "- router would have answered: {router}"
        ),
        "active": (
            "**Active:** {total} recorded requests\n"
            "- forwarded to Hermes: {chat}\n"
            "- answered by the router: {router}\n"
            "- Hermes errors: {errors}"
        ),
        "observe_errors": "Observe errors: {count}",
        "router_errors": "Internal router errors (answered neutrally, not sent to Hermes): {count}",
        "footer": "Since {minutes} min (HA start or reset). Test requests are not counted.",
    },
}


def statistics_summary(lang: str, snap: dict[str, Any], mode: str) -> str:
    """Short human summary derived only from the anonymous counters."""
    texts = _SUMMARY[lang]
    decisions: dict[str, dict[str, int]] = snap["decisions"]
    hermes: dict[str, int] = snap["hermes_results"]
    parts: list[str] = []
    if mode == "off":
        parts.append(texts["off_note"])
    totals = {m: sum(counts.values()) for m, counts in decisions.items()}
    if totals["observe"] == 0 and totals["active"] == 0:
        parts.append(texts["empty"])
    if totals["observe"]:
        counts = decisions["observe"]
        parts.append(
            texts["observe"].format(
                total=totals["observe"],
                chat=counts["CHAT"],
                router=totals["observe"] - counts["CHAT"],
            )
        )
    if totals["active"]:
        counts = decisions["active"]
        parts.append(
            texts["active"].format(
                total=totals["active"],
                chat=counts["CHAT"],
                router=totals["active"] - counts["CHAT"],
                errors=sum(value for key, value in hermes.items() if key != "ok"),
            )
        )
    if snap["observe_errors"]:
        parts.append(texts["observe_errors"].format(count=snap["observe_errors"]))
    if snap.get("router_errors"):
        parts.append(texts["router_errors"].format(count=snap["router_errors"]))
    parts.append(texts["footer"].format(minutes=int(snap["seconds_since_reset"]) // 60))
    return "\n\n".join(parts)


def statistics_details(lang: str, snap: dict[str, Any]) -> str:
    """Per-mode route counters, Hermes results and latency classes with human labels."""
    heading = {
        "de": ("Beobachten", "Aktiv", "Hermes-Ergebnisse (aktiv)", "Hermes-Antwortzeit (aktiv)"),
        "en": ("Observe", "Active", "Hermes results (active)", "Hermes response time (active)"),
    }[lang]
    lines: list[str] = []
    for title, mode in ((heading[0], "observe"), (heading[1], "active")):
        lines.append(f"**{title}**")
        for lane, count in snap["decisions"][mode].items():
            lines.append(f"- {ROUTE_LABELS[lang][lane]} (`{lane}`): {count}")
    lines.append(f"**{heading[2]}**")
    for key, count in snap["hermes_results"].items():
        lines.append(f"- {HERMES_RESULT_LABELS[lang][key]} (`{key}`): {count}")
    lines.append(f"**{heading[3]}**")
    for key, count in snap["hermes_latency"].items():
        lines.append(f"- {LATENCY_LABELS[lang][key]}: {count}")
    return "\n".join(lines)
