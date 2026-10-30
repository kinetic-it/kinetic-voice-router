"""R3: Betriebsart, Beobachtung, Simulation, Laufzeitstatistik, Sprachkorpus.

Reiner Router-Kern, Standardbibliothek, keine HA-Instanz.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router import (  # noqa: E402
    FailureCode,
    Lane,
    OperatingMode,
    RouterBridge,
    RuntimeStats,
    operating_mode,
    simulate,
)

# Umstellungen, Komposita, Hoeflichkeit, an/aus/on/off, STT-Varianten
CONTROL_VARIANTS = [
    "Das Licht im Flur mach bitte aus",
    "Die Wohnzimmerlampe bitte einschalten",
    "Schlafzimmerlicht aus",
    "Würdest du bitte das Licht ausschalten?",
    "Könntest du die Heizung höher drehen?",
    "Mach mal bitte die Lampe an",
    "Licht im Bad an bitte",
    "Schalter Wohnzimmer aus",
    "schalt die stehlampe aus",
    "Bitte die Rollläden runter",
    "Fernseher aus",
    "Die Kaffeemaschine anschalten",
    "Kannst du mal das Licht ausmachen",
    "Mach das Deckenlicht heller",
    "Ventilator on",
    "Mach die Musik leiser",
    "Dreh die Heizung auf 21 Grad",
    "Mach mir das Licht an",
]
STATUS_VARIANTS = [
    "Ist das Wohnzimmerlicht noch an?",
    "Brennt im Flur noch Licht?",
    "Sind alle Fenster zu?",
    "Ist die Haustür abgeschlossen?",
    "Läuft die Waschmaschine noch?",
    "Wie ist der Status der Heizung?",
    "Hab ich das Licht angelassen?",
    "Ist der Staubsauger fertig?",
]
# Negative Gegenbeispiele: muessen Hermes erreichen
KNOWLEDGE_NEGATIVES = [
    "Wie schaltet man eine Wärmepumpe aus?",
    "Warum geht das Licht im Kühlschrank aus?",
    "Was bedeutet off auf Deutsch?",
    "Ist es schlimm, das Licht anzulassen?",
    "Ich mache das Licht immer aus, wenn ich gehe",
    "Erzähl mir, wie eine Steckdose funktioniert",
    "Was ist besser, LED oder Halogen?",
    "Wie viel Strom braucht ein Fernseher im Standby?",
    "Wer hat den Staubsauger erfunden?",
    "Stell dir vor, die Lampe könnte sprechen",
    "Mach dir keine Sorgen",
    "Spiel mir das Lied vom Tod nicht vor",
    "Wie lange darf ein Aquarium ohne Licht sein?",
    "Kannst du mir erklären, wie ein Thermostat funktioniert?",
    "Ist Licht schneller als Schall?",
    "Zeig mir, wie man eine Lampe anschließt",
    "Gute Nacht, mach's gut",
    "Danke, das reicht",
    "Was kostet eine neue Waschmaschine?",
    "Ich mache das Licht aus",
    "Muss man die Heizung entlüften?",
    "Kann man die Lampe dimmen?",
    "Das Projekt ist abgeschlossen",
    "Ist das Essen fertig?",
    "Hab ich dir schon von meinem Urlaub erzählt?",
    "Die Waschmaschine von Bosch ist gut",
    "Bitte erzähl mir einen Witz",
]


class LanguageCorpus(unittest.TestCase):
    def test_control_variants(self):
        for text in CONTROL_VARIANTS:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CONTROL_FALLBACK)
                self.assertFalse(decision.may_call_ha_action)

    def test_status_variants(self):
        for text in STATUS_VARIANTS:
            with self.subTest(text=text):
                self.assertEqual(simulate(text, "de").rule_id, "R-STATUS-01")

    def test_knowledge_negatives_reach_hermes(self):
        for text in KNOWLEDGE_NEGATIVES:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CHAT)
                self.assertTrue(decision.may_call_hermes)


class OperatingModes(unittest.TestCase):
    def test_mode_parsing_fail_closed(self):
        cases = [
            ({"mode": "off"}, OperatingMode.OFF),
            ({"mode": "observe"}, OperatingMode.OBSERVE),
            ({"mode": "active"}, OperatingMode.ACTIVE),
            ({"mode": "Aktiv"}, OperatingMode.OFF),
            ({"mode": None}, OperatingMode.OFF),
            ({"mode": True}, OperatingMode.OFF),
            # 0.3.0 ohne mode: nur echtes True bleibt aktiv
            ({"router_enabled": True}, OperatingMode.ACTIVE),
            ({"router_enabled": "true"}, OperatingMode.OFF),
            ({}, OperatingMode.OFF),
            (None, OperatingMode.OFF),
            # mode gewinnt ueber Altflag, auch wenn kaputt
            ({"mode": "off", "router_enabled": True}, OperatingMode.OFF),
            ({"mode": "x", "router_enabled": True}, OperatingMode.OFF),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                self.assertIs(operating_mode(options), expected)

    def test_bridge_flags_per_mode(self):
        for mode, enabled, observing in (
            ("off", False, False),
            ("observe", False, True),
            ("active", True, False),
        ):
            with self.subTest(mode=mode):
                bridge = RouterBridge.from_options({"mode": mode})
                self.assertEqual((bridge.enabled, bridge.observing), (enabled, observing))
                self.assertEqual(bridge.api_version, 2)

    def test_async_handle_only_in_active(self):
        async def hermes() -> str:
            raise AssertionError("must not be called")

        for mode in ("off", "observe"):
            bridge = RouterBridge.from_options({"mode": mode})
            reply = asyncio.run(
                bridge.async_handle(
                    text="Ist das Licht aus?",
                    language="de",
                    conversation_id="c",
                    call_hermes=hermes,
                    hermes_errors=(),
                )
            )
            self.assertIsNone(reply)


class ObserveAndSimulate(unittest.TestCase):
    def test_observe_counts_without_state(self):
        bridge = RouterBridge.from_options({"mode": "observe"})
        bridge.observe(text="Licht", language="de")
        bridge.observe(text="Ja", language="de")
        bridge.observe(text="Ist das Licht aus?", language="de")
        self.assertEqual(bridge.store._entries, {})
        counts = bridge.stats.snapshot()["decisions"]["observe"]
        self.assertEqual(
            counts, {"CHAT": 0, "CONTROL_FALLBACK": 1, "EXPLAIN_LAST": 0, "UNKNOWN": 2}
        )

    def test_observe_noop_outside_observe_mode(self):
        for mode in ("off", "active"):
            bridge = RouterBridge.from_options({"mode": mode})
            bridge.observe(text="Ist das Licht aus?", language="de")
            self.assertEqual(sum(bridge.stats.snapshot()["decisions"]["observe"].values()), 0)

    def test_observe_never_raises(self):
        bridge = RouterBridge.from_options({"mode": "observe"})
        for payload in (None, 42, b"x", "x" * 10_000, "\x00"):
            bridge.observe(text=payload, language=None)
        snap = bridge.stats.snapshot()
        self.assertEqual(snap["observe_errors"], 0)
        self.assertEqual(sum(snap["decisions"]["observe"].values()), 5)

    def test_simulate_is_stateless_and_actionless(self):
        first = simulate("Licht", "de")
        second = simulate("Ja", "de")
        self.assertEqual(first.reason_code.value, "AMBIGUOUS_FRAGMENT")
        self.assertEqual(second.reason_code.value, "BARE_CONFIRMATION")
        self.assertFalse(first.may_call_ha_action or second.may_call_ha_action)


class Statistics(unittest.TestCase):
    def test_counters_fixed_keys_and_reset(self):
        now = [100.0]
        stats = RuntimeStats(clock=lambda: now[0])
        stats.record_decision("active", Lane.CHAT)
        stats.record_decision("bogus", Lane.CHAT)
        stats.record_hermes(None, 1.0)
        stats.record_hermes(FailureCode.PROVIDER_TIMEOUT, 61.0)
        stats.record_hermes(FailureCode.HA_UNREACHABLE, 1.0)  # nie Hermes-Klasse: ignoriert
        now[0] = 400.0
        snap = stats.snapshot()
        self.assertEqual(snap["scope"], "process_lifetime")
        self.assertEqual(snap["seconds_since_reset"], 300)
        self.assertEqual(snap["decisions"]["active"]["CHAT"], 1)
        self.assertEqual(
            snap["hermes_results"],
            {
                "ok": 1,
                "PROVIDER_TIMEOUT": 1,
                "PROVIDER_UNAVAILABLE": 0,
                "AUTH_FAILED": 0,
                "UNKNOWN_FAILURE": 0,
            },
        )
        self.assertEqual(
            snap["hermes_latency"], {"under_2s": 2, "under_5s": 0, "under_15s": 0, "over_15s": 1}
        )
        stats.reset()
        self.assertEqual(sum(stats.snapshot()["decisions"]["active"].values()), 0)
        self.assertEqual(stats.snapshot()["seconds_since_reset"], 0)

    def test_snapshot_contains_only_numbers(self):
        stats = RuntimeStats()

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertIsInstance(key, str)
                    walk(item)
            else:
                self.assertTrue(isinstance(value, int) or value == "process_lifetime")

        walk(stats.snapshot())


if __name__ == "__main__":
    unittest.main()
