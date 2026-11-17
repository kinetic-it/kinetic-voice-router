"""Autorisierter Wecker-Pfad des Kinetic Voice Router (R05).

Der Router fuehrt weiterhin **keine Geraeteaktionen** aus. Dieses Modul bildet
ausschliesslich Weckerbefehle auf genau eine, fest verdrahtete HA-Aktion ab:

    nabu_alarm_writer.execute_voice   (operation set|delete|stop)

Alles andere bleibt unveraendert auf dem bisherigen sicheren Pfad
(Kind.ACTION -> CONTROL_FALLBACK, keine Ausfuehrung).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DOMAIN = "nabu_alarm_writer"
SERVICE = "execute_voice"
# Einzige autorisierte Ziele. Jede Erweiterung ist eine Sicherheitsentscheidung.
AUTHORIZED_TARGETS = frozenset({(DOMAIN, SERVICE)})

MIN_DELAY_SECONDS = 60
MAX_DELAY_SECONDS = 24 * 3600

# Nur Wecker sind Wecker. "Timer" gehoert Home Assistant und darf nie in den
# Weckerpfad fallen (eindeutige Trennung beider Begriffe).
_NOUNS = frozenset({"wecker"})
_SET_VERBS = frozenset(
    {
        "stelle",
        "stell",
        "stellen",
        "setze",
        "setz",
        "setzen",
        "starte",
        "start",
        "starten",
        "erstelle",
        "erstell",
    }
)
_DELETE_VERBS = frozenset({"lösche", "lösch", "losche", "entferne", "entfern", "abbrechen"})
_STOP_VERBS = frozenset({"stoppe", "stopp", "stoppen", "beende", "beend", "aus", "ausmachen"})

_REL_PREFIX = re.compile(
    r"\b(?:in|nach)\s+(?P<num>\d{1,3}|ein(?:e|er|en)?|einer\s+halben|halbe[nmrs]?)\s*"
    r"(?P<unit>sekunden?|sek|minuten?|min|stunden?|std|h)\b"
)
_REL_SUFFIX = re.compile(
    r"\b(?P<num>\d{1,3})\s*(?P<unit>sekunden?|sek|minuten?|min|stunden?|std)\s+"
    r"(?:ab\s+jetzt|von\s+jetzt)\b"
)
_GLEICH = re.compile(r"\bgleich\b")
_VIERTEL_VOR = re.compile(r"\bviertel\s+vor\s+(?P<h>\d{1,2})\b")
_VIERTEL_NACH = re.compile(r"\bviertel\s+nach\s+(?P<h>\d{1,2})\b")
_HALB = re.compile(r"\bhalb\s+(?P<h>\d{1,2})\b")
_UHR = re.compile(r"\b(?:(?:um|auf)\s+)?(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*uhr\b")
_UM_MIN = re.compile(r"\b(?:um|auf)\s+(?P<h>\d{1,2})(?:[:.]|\s+)(?P<m>\d{2})\b")
_UM = re.compile(r"\b(?:um|auf)\s+(?P<h>\d{1,2})\b")
_MORGEN = re.compile(r"\bmorgen\b")
_HEUTE = re.compile(r"\bheute\b")
_MEHRFACH = re.compile(r"\b(?:und|dann|danach)\b")

_UNITS = {
    "sekunde": 1,
    "sekunden": 1,
    "sek": 1,
    "minute": 60,
    "minuten": 60,
    "min": 60,
    "stunde": 3600,
    "stunden": 3600,
    "std": 3600,
    "h": 3600,
}
_WORTZAHLEN = {
    "ein": 1,
    "eine": 1,
    "einer": 1,
    "einen": 1,
    "einem": 1,
    "halbe": 0.5,
    "halber": 0.5,
    "halben": 0.5,
    "halbes": 0.5,
}


@dataclass(frozen=True)
class AlarmAction:
    """Eine einzelne, autorisierte Weckeraktion."""

    operation: str  # set | delete | stop
    rule_id: str
    speak: str
    when_local: str | None = None  # "YYYY-MM-DD HH:MM" (Europe/Berlin), nur bei set
    domain: str = field(default=DOMAIN, init=False)
    service: str = field(default=SERVICE, init=False)

    @property
    def data(self) -> Mapping[str, object]:
        daten: dict[str, object] = {"operation": self.operation}
        if self.when_local is not None:
            daten["alarm_time"] = self.when_local
        return daten


def _sprechzeit(wert: datetime) -> str:
    return f"{wert.hour}:{wert.minute:02d}"


def _zahl(roh: str) -> float | None:
    roh = roh.strip()
    if roh.isdigit():
        return float(roh)
    roh = roh.replace("einer halben", "halben")
    return _WORTZAHLEN.get(roh)


def _relative(text: str, jetzt: datetime) -> tuple[datetime, str] | None:
    treffer = _REL_PREFIX.search(text) or _REL_SUFFIX.search(text)
    if treffer is not None:
        anzahl = _zahl(treffer.group("num"))
        einheit = _UNITS.get(treffer.group("unit"))
        if anzahl is None or einheit is None:
            return None
        sekunden = anzahl * einheit
    elif _GLEICH.search(text):
        sekunden = 60
    else:
        return None
    if sekunden < MIN_DELAY_SECONDS or sekunden > MAX_DELAY_SECONDS:
        return None
    ziel = jetzt + timedelta(seconds=sekunden)
    ziel = ziel.replace(second=0, microsecond=0)
    if ziel <= jetzt:
        ziel += timedelta(minutes=1)
    return ziel, "R-ALARM-SET-RELATIV"


def _lokal_valid(tag: datetime, stunde: int, minute: int) -> datetime | None:
    """Lokale Uhrzeit als naiver Zeitpunkt.

    Bereich wird geprueft; die Zeitzonenabbildung (inkl. DST) macht Home
    Assistant beim Ausfuehren der Aktion.
    """
    if not (0 <= stunde <= 23 and 0 <= minute <= 59):
        return None
    return tag.replace(hour=stunde, minute=minute, second=0, microsecond=0)


def _uhrzeit_aus_text(text: str) -> tuple[int | None, int | None]:
    """Erste brauchbare Uhrzeit aus den Mustern lesen.

    Der Router arbeitet auf normalisiertem Text; dort wird "15:30" zu "15 30".
    Deshalb werden alle Muster geprueft und der erste gueltige Wert genommen,
    statt beim ersten (moeglicherweise unbrauchbaren) Treffer abzubrechen.
    """
    for muster in (_UHR, _UM_MIN, _UM):
        for treffer in muster.finditer(text):
            stunde = int(treffer.group("h"))
            minute = int(treffer.groupdict().get("m") or 0)
            if 0 <= stunde <= 23 and 0 <= minute <= 59:
                return stunde, minute
    return None, None


def _absolute(text: str, jetzt: datetime) -> tuple[datetime, str] | None:
    stunde = minute = None
    regel = "R-ALARM-SET-ABSOLUT"

    treffer = _VIERTEL_VOR.search(text)
    if treffer is not None:
        stunde, minute, regel = int(treffer.group("h")) - 1, 45, "R-ALARM-SET-VIERTEL"
    else:
        treffer = _VIERTEL_NACH.search(text)
        if treffer is not None:
            stunde, minute, regel = int(treffer.group("h")), 15, "R-ALARM-SET-VIERTEL"
        else:
            treffer = _HALB.search(text)
            if treffer is not None:
                stunde, minute, regel = int(treffer.group("h")) - 1, 30, "R-ALARM-SET-HALB"
            else:
                stunde, minute = _uhrzeit_aus_text(text)
                if stunde is None or minute is None:
                    return None

    if stunde is None or minute is None or not (0 <= stunde <= 23 and 0 <= minute <= 59):
        return None

    morgen = _MORGEN.search(text) is not None
    heute = _HEUTE.search(text) is not None
    tage = 1 if morgen else 0
    for _ in range(0, 3):
        ziel = _lokal_valid(jetzt + timedelta(days=tage), stunde, minute)
        if ziel is None:
            return None
        if ziel > jetzt:
            if ziel - jetzt > timedelta(seconds=MAX_DELAY_SECONDS):
                return None
            return ziel, regel
        if heute and not morgen:
            # "heute um 6" liegt hinter uns -> nicht in die Vergangenheit planen
            tage += 1
            continue
        tage += 1
    return None


def parse_alarm(text: object, jetzt: datetime) -> AlarmAction | None:
    """Bildet einen Weckerbefehl ab oder gibt None zurueck (kein Eingriff)."""
    if not isinstance(text, str) or not isinstance(jetzt, datetime) or jetzt.tzinfo is not None:
        return None
    if not text.strip():
        return None
    # Spracherkennung liefert Gross-/Kleinschreibung gemischt ("Stelle einen Wecker auf
    # 15:30 Uhr."). Alle Muster sind klein geschrieben, deshalb hier einmal normalisieren.
    klein = text.lower()
    # Satzzeichen duerfen die Wortpruefung nicht brechen ("Loesche den Wecker.").
    woerter = re.findall(r"[a-z0-9\u00e4\u00f6\u00fc\u00df]+", klein)
    if not any(w in _NOUNS for w in woerter):
        return None
    # Mehrteilige Anfragen ("... und schalte das Licht an") bleiben beim alten Pfad.
    if _MEHRFACH.search(klein):
        return None

    if any(w in _DELETE_VERBS for w in woerter):
        return AlarmAction("delete", "R-ALARM-DELETE", "Wecker gelöscht.")
    if any(w in _STOP_VERBS for w in woerter):
        return AlarmAction("stop", "R-ALARM-STOP", "Wecker gestoppt.")

    if not (any(w in _SET_VERBS for w in woerter) or woerter[0] in _NOUNS):
        return None

    relativ = _relative(klein, jetzt)
    if relativ is not None:
        ziel, regel = relativ
        return AlarmAction(
            "set", regel, f"Wecker steht auf {_sprechzeit(ziel)}.", ziel.strftime("%Y-%m-%d %H:%M")
        )
    absolut = _absolute(klein, jetzt)
    if absolut is not None:
        ziel, regel = absolut
        return AlarmAction(
            "set", regel, f"Wecker steht auf {_sprechzeit(ziel)}.", ziel.strftime("%Y-%m-%d %H:%M")
        )
    return None
