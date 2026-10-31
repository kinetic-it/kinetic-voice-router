"""Synthetic, independent ASM learning/abuse tests; no real devices or identities."""

from __future__ import annotations

import pathlib
import sys
import unittest

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router.speech_memory import SpeechMemory  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class SpeechMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.memory = SpeechMemory(clock=self.clock)

    def test_no_learning_without_confirmation(self) -> None:
        self.assertTrue(self.memory.propose("a", "Mulahn", "Mulan"))
        self.assertEqual(self.memory.export_confirmed()["rules"], [])
        self.assertEqual(
            self.memory.apply("Erzähl mir von Mulahn", enabled=True),
            "Erzähl mir von Mulahn",
        )

    def test_explicit_confirmation_and_opt_in(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.assertTrue(self.memory.confirm("a", "Ja"))
        self.assertEqual(
            self.memory.apply("Erzähl mir von Mulahn", enabled=True),
            "Erzähl mir von Mulan",
        )
        self.assertEqual(
            self.memory.apply("Erzähl mir von Mulahn"),
            "Erzähl mir von Mulahn",
        )

    def test_whole_word_only(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.memory.confirm("a", "Ja")
        self.assertEqual(
            self.memory.apply("Erzähl mir von Mulahns Freunden", enabled=True),
            "Erzähl mir von Mulahns Freunden",
        )
        self.assertEqual(
            self.memory.apply("Erzähl mir von Mulahn!", enabled=True),
            "Erzähl mir von Mulan!",
        )

    def test_wrong_session_decline_or_double_confirmation_rejected(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.assertFalse(self.memory.confirm("b", "Ja"))
        self.assertFalse(self.memory.confirm("a", "Nein"))
        self.assertFalse(self.memory.confirm("a", "Ja"))

    def test_timeout(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.clock.now += 61
        self.assertFalse(self.memory.confirm("a", "Ja"))

    def test_broken_stt_never_autolearned(self) -> None:
        for heard in ("T.", "T", "A.", "an", "aus", "Stopp", "123", "\x00"):
            with self.subTest(heard=heard):
                self.assertFalse(self.memory.propose("a", heard, "Tee"))

    def test_no_rewrite_for_actions_or_state_queries(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.memory.confirm("a", "Ja")
        for utterance in (
            "Schalte Mulahn ein",
            "Ist Mulahn an?",
            "Status Mulahn",
            "Mach Mulahn aus",
        ):
            with self.subTest(utterance=utterance):
                self.assertEqual(self.memory.apply(utterance, enabled=True), utterance)

    def test_protected_targets_or_same_word(self) -> None:
        self.assertFalse(self.memory.propose("a", "Mulahn", "Lampe"))
        self.assertFalse(self.memory.propose("a", "Mulan", "MULAN"))
        self.assertFalse(self.memory.propose("a", "Aus", "Mulan"))

    def test_export_import_delete(self) -> None:
        self.memory.propose("a", "Mulahn", "Mulan")
        self.memory.confirm("a", "Ja")
        record = self.memory.export_confirmed()
        self.assertNotIn("conversation_id", repr(record))
        recovered = SpeechMemory()
        self.assertEqual(recovered.import_confirmed(record), 1)
        self.assertTrue(recovered.delete("MULAHN"))
        self.assertEqual(recovered.export_confirmed()["rules"], [])

    def test_invalid_import(self) -> None:
        self.assertEqual(self.memory.import_confirmed({"schema": 999, "rules": []}), 0)
        self.assertEqual(self.memory.import_confirmed({"schema": 1, "rules": "bad"}), 0)
        self.assertEqual(
            self.memory.import_confirmed(
                {"schema": 1, "rules": [{"heard": "T.", "intended": "Tee"}]}
            ),
            0,
        )

    def test_no_session(self) -> None:
        self.assertFalse(self.memory.propose(None, "Mulahn", "Mulan"))
        self.assertFalse(self.memory.propose("", "Mulahn", "Mulan"))


if __name__ == "__main__":
    unittest.main()
