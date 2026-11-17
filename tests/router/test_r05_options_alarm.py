"""G5-Korrektur: alarm_actions muss den produktiven Adapter erreichen.

Prueft die reine Optionsauswertung und statisch, dass der produktive
Adapter genau diese Auswertung nutzt (kein zweiter Pfad).
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router.router import RouterConfig  # noqa: E402


class AlarmOptionWiring(unittest.TestCase):
    def test_flag_enables_alarm_path(self) -> None:
        config = RouterConfig.from_mapping({"mode": "active", "alarm_actions": True})
        self.assertTrue(config.router_enabled)
        self.assertTrue(config.alarm_enabled)

    def test_missing_flag_stays_closed(self) -> None:
        self.assertFalse(RouterConfig.from_mapping({"mode": "active"}).alarm_enabled)

    def test_non_bool_flag_stays_closed(self) -> None:
        for wert in (1, "true", "yes", None):
            with self.subTest(wert=wert):
                config = RouterConfig.from_mapping({"mode": "active", "alarm_actions": wert})
                self.assertFalse(config.alarm_enabled)

    def test_off_mode_keeps_router_disabled(self) -> None:
        config = RouterConfig.from_mapping({"mode": "off", "alarm_actions": True})
        self.assertFalse(config.router_enabled)

    def test_adapter_uses_from_mapping(self) -> None:
        quelle = (ROUTER_DIR / "voice_router" / "adapter.py").read_text()
        baum = ast.parse(quelle)
        treffer = [
            knoten
            for knoten in ast.walk(baum)
            if isinstance(knoten, ast.FunctionDef) and knoten.name == "from_options"
        ]
        self.assertEqual(len(treffer), 1)
        rumpf = ast.get_source_segment(quelle, treffer[0])
        self.assertIn("RouterConfig.from_mapping(options)", rumpf)
        self.assertNotIn("RouterConfig(router_enabled=", rumpf)


if __name__ == "__main__":
    unittest.main()
