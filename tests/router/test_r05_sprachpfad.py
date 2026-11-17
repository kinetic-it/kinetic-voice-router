"""Gezielte Nachweise fuer den produktiven Sprachtest (Gross-/Kleinschreibung,
Satzzeichen, "auf ... Uhr") und fuer die Trennung Wecker/Timer.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from datetime import datetime

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router.alarm import parse_alarm  # noqa: E402

JETZT = datetime(2026, 11, 17, 15, 0)


class ParserAkzeptiertGesprocheneSaetze(unittest.TestCase):
    def test_relative_minuten_grossgeschrieben(self) -> None:
        plan = parse_alarm("Stelle einen Wecker in 2 Minuten.", JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.operation, "set")
        self.assertEqual(plan.when_local, "2026-11-17 15:02")

    def test_absolute_zeit_auf_mit_uhr(self) -> None:
        plan = parse_alarm("Stelle einen Wecker auf 15:30 Uhr.", JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.when_local, "2026-11-17 15:30")

    def test_absolute_zeit_auf_ohne_uhr(self) -> None:
        plan = parse_alarm("Stelle einen Wecker auf 15:30.", JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.when_local, "2026-11-17 15:30")

    def test_absolute_zeit_volle_stunde(self) -> None:
        plan = parse_alarm("Wecker auf 7 Uhr.", JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.when_local, "2026-11-18 07:00")

    def test_loeschen_mit_satzzeichen(self) -> None:
        plan = parse_alarm("Lösche den Wecker.", JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.operation, "delete")


class TrennungWeckerTimer(unittest.TestCase):
    def test_timer_ist_kein_wecker(self) -> None:
        for satz in (
            "Stelle einen Timer auf 5 Minuten.",
            "Timer 5 Minuten.",
            "Starte einen Küchentimer.",
        ):
            with self.subTest(satz=satz):
                self.assertIsNone(parse_alarm(satz, JETZT))

    def test_ohne_wecker_kein_weckerpfad(self) -> None:
        self.assertIsNone(parse_alarm("Stelle die Musik lauter.", JETZT))
        self.assertIsNone(parse_alarm("Wie ist der Status der Heizung?", JETZT))


class NormalisierterText(unittest.TestCase):
    """Der Router uebergibt normalisierten Text; dort wird "15:30" zu "15 30"."""

    def test_absolut_nach_normalisierung(self) -> None:
        from voice_router.classify import normalize

        for roh, erwartet in (
            ("Stelle einen Wecker auf 15:30 Uhr.", "2026-11-17 15:30"),
            ("Stelle einen Wecker auf 16:45 Uhr.", "2026-11-17 16:45"),
            ("Stelle einen Wecker um 7 Uhr.", "2026-11-18 07:00"),
            ("Stelle einen Wecker auf 15:30.", "2026-11-17 15:30"),
        ):
            with self.subTest(roh=roh):
                plan = parse_alarm(normalize(roh), JETZT)
                self.assertIsNotNone(plan)
                self.assertEqual(plan.when_local, erwartet)

    def test_relativ_nach_normalisierung(self) -> None:
        from voice_router.classify import normalize

        plan = parse_alarm(normalize("Stelle einen Wecker in 2 Minuten."), JETZT)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.when_local, "2026-11-17 15:02")


if __name__ == "__main__":
    unittest.main()
