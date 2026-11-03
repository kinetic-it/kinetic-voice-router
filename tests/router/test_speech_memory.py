"""Adaptive Speech Memory core: validation, correction parsing, safe application,
categories, conflicts, persistence contract and the shared session state.

Synthetic data only; no devices, persons or recordings.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router.model import ClarificationKind  # noqa: E402
from voice_router.speech_memory import (  # noqa: E402
    MAX_ENTRIES,
    Category,
    Correction,
    Entry,
    LoadError,
    Rejection,
    Source,
    SpeechMemory,
    check_pair,
    is_confirmation,
    is_decline,
    load_entries,
    parse_correction,
    suggested_category,
)
from voice_router.state import DIALOGUE_TTL_SECONDS, ProposalStatus, SessionStore  # noqa: E402

TODAY = "2026-10-31"
PREVIOUS = "Erzähl mir etwas über Mulahn"


def memory_with(*pairs: tuple[str, str, Category]) -> SpeechMemory:
    memory = SpeechMemory()
    for heard, intended, category in pairs:
        result = memory.add(heard, intended, category=category, source=Source.MANUAL, today=TODAY)
        assert isinstance(result, Entry), result
    return memory


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class PairValidation(unittest.TestCase):
    def test_valid_names_and_phrases(self):
        for heard, intended in (
            ("Mulahn", "Mulan"),
            ("Ronja Räuber Tochter", "Ronja Räubertochter"),
            ("Pokahontas", "Pocahontas"),
            ("Saint-Exupéry", "Saint-Exupéry Buch"),
        ):
            with self.subTest(heard=heard):
                self.assertIsInstance(check_pair(heard, intended), tuple)

    def test_single_letters_and_fragments_are_never_pairs(self):
        for heard in ("T", "T.", "A.", "Ta", "ab"):
            with self.subTest(heard=heard):
                self.assertEqual(check_pair(heard, "Tee"), Rejection.TOO_SHORT)

    def test_device_room_control_and_confirmation_words_are_protected(self):
        for heard, intended in (
            ("Licht", "Lich"),
            ("Lampen", "Lampe"),
            ("Wohnzimmer", "Wohnzimer"),
            ("Mulahn", "Wohnzimmer"),
            ("Stopp", "Stop"),
            ("aus", "raus"),
            ("Ja mach das", "Jamach"),
            ("Steckdosen", "Steckdose"),
            ("Heizung", "Heitzung"),
            ("Status", "Staus"),
            ("Musikk", "Musik"),
        ):
            with self.subTest(heard=heard, intended=intended):
                self.assertEqual(check_pair(heard, intended), Rejection.PROTECTED)

    def test_invalid_shapes(self):
        for heard, intended in (
            ("", "Mulan"),
            ("Mulahn", ""),
            ("Mul4hn", "Mulan"),
            ("Mulahn!", "Mulan"),
            ("eins zwei drei vier", "Mulan"),
            ("x" * 41, "Mulan"),
            (None, "Mulan"),
            ("Mulahn", 7),
        ):
            with self.subTest(heard=heard):
                self.assertIn(check_pair(heard, intended), (Rejection.INVALID, Rejection.TOO_SHORT))
        self.assertEqual(check_pair("Mulan", "mulan"), Rejection.SAME)


class CorrectionParsing(unittest.TestCase):
    def test_supported_correction_forms(self):
        for sentence in (
            "Nein, ich meinte Mulan.",
            "ich meine Mulan",
            "Ich habe Mulan gesagt",
            "gemeint war Mulan",
            "Nicht Mulahn, sondern Mulan",
            "Mulan, nicht Mulahn",
        ):
            with self.subTest(sentence=sentence):
                self.assertEqual(
                    parse_correction(sentence, PREVIOUS), Correction("Mulahn", "Mulan")
                )

    def test_misheard_word_must_be_reliably_known(self):
        # no similar word in the previous turn
        self.assertIsNone(parse_correction("ich meinte Pocahontas", PREVIOUS))
        # two similar candidates: do not guess
        self.assertIsNone(
            parse_correction("ich meinte Mulan", "Erzähl mir etwas über Mulahn und Mulahm")
        )
        # explicitly named word that was not said
        self.assertIsNone(parse_correction("nicht Mulam, sondern Mulan", PREVIOUS))
        # intended word was already there: nothing was misheard
        self.assertIsNone(parse_correction("ich meinte Mulan", "Erzähl mir etwas über Mulan"))
        # no previous turn
        self.assertIsNone(parse_correction("ich meinte Mulan", None))

    def test_multi_word_names(self):
        self.assertEqual(
            parse_correction(
                "ich meinte Ronja Räubertochter", "Erzähl mir von Ronja Räuber Tochter"
            ),
            Correction("Ronja Räuber Tochter", "Ronja Räubertochter"),
        )

    def test_no_learning_from_device_or_status_turns(self):
        for previous in (
            "Schalte Mulahn ein",
            "Ist Mulahn an?",
            "Mach das Licht im Mulahn an",
            "Wie ist der Status von Mulahn",
        ):
            with self.subTest(previous=previous):
                self.assertIsNone(parse_correction("ich meinte Mulan", previous))

    def test_no_learning_of_protected_targets(self):
        self.assertIsNone(parse_correction("Nein, ich meinte das Licht", "Erzähl mir von Lich"))
        self.assertIsNone(parse_correction("ich meinte Wohnzimmer", "Erzähl was über Wohnzimer"))

    def test_correction_mixed_with_command_is_ignored(self):
        self.assertIsNone(parse_correction("ich meinte Mulan und schalte das Licht an", PREVIOUS))

    def test_one_letter_answer_is_not_a_correction(self):
        self.assertIsNone(parse_correction("T.", "Möchtest du Kaffee oder Tee?"))
        self.assertIsNone(parse_correction("ich meinte T", "Kaffee oder Tea"))

    def test_confirmation_and_decline_words(self):
        for yes in ("Ja", "ja bitte", "Genau.", "Merk dir das", "Ja, merk dir das!"):
            self.assertTrue(is_confirmation(yes), yes)
        for no in ("Nein", "nein danke", "Lieber nicht", "nicht merken"):
            self.assertTrue(is_decline(no), no)
        for other in ("Ja mach das", "Ja schalte es ein", "Tee", "vielleicht", None):
            self.assertFalse(is_confirmation(other), other)


class Application(unittest.TestCase):
    def setUp(self):
        self.memory = memory_with(
            ("Mulahn", "Mulan", Category.STT),
            ("Ronja Räuber Tochter", "Ronja Räubertochter", Category.NAME),
        )

    def test_harmless_conversation_is_corrected(self):
        self.assertEqual(
            self.memory.apply("Erzähl mir etwas über mulahn"), "Erzähl mir etwas über Mulan"
        )
        self.assertEqual(
            self.memory.apply("Wer ist Ronja Räuber Tochter?"), "Wer ist Ronja Räubertochter?"
        )

    def test_whole_words_only(self):
        self.assertIsNone(self.memory.apply("Erzähl mir etwas über Mulahns Reise"))

    def test_device_commands_and_status_are_never_rewritten(self):
        for text in (
            "Schalte Mulahn an",
            "Ist Mulahn an?",
            "Mulahn aus",
            "Mach Mulahn heller",
            "Licht im Mulahn an",
            "Ja mach das",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.memory.apply(text))

    def test_ambiguous_entries_are_never_applied(self):
        memory = memory_with(("Mehr", "Meer", Category.AMBIGUOUS))
        self.assertIsNone(memory.apply("Erzähl mir mehr über das Mehr"))

    def test_nothing_to_change(self):
        self.assertIsNone(self.memory.apply("Wie spät ist es?"))
        self.assertIsNone(SpeechMemory().apply("Erzähl mir etwas über Mulahn"))
        self.assertIsNone(self.memory.apply(None))

    def test_no_chain_application(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        self.assertEqual(
            memory.add(
                "Mulan", "Pocahontas", category=Category.STT, source=Source.MANUAL, today=TODAY
            ),
            Rejection.CHAIN,
        )


class LexiconRules(unittest.TestCase):
    def test_duplicate_is_no_op_and_conflict_is_refused(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        same = memory.add(
            "mulahn", "mulan", category=Category.STT, source=Source.MANUAL, today=TODAY
        )
        self.assertIsInstance(same, Entry)
        self.assertEqual(len(memory), 1)
        self.assertEqual(
            memory.add(
                "Mulahn", "Moulin", category=Category.STT, source=Source.MANUAL, today=TODAY
            ),
            Rejection.CONFLICT,
        )
        self.assertEqual(memory.get("Mulahn").intended, "Mulan")

    def test_explicit_replace_and_update(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        replaced = memory.add(
            "Mulahn",
            "Moulin",
            category=Category.NAME,
            source=Source.DIALOGUE,
            today=TODAY,
            replace_existing=True,
        )
        self.assertEqual(replaced.intended, "Moulin")
        updated = memory.update("Mulahn", "Mulan", category=Category.TERM, today=TODAY)
        self.assertEqual((updated.intended, updated.category), ("Mulan", Category.TERM))
        self.assertEqual(
            memory.update("Unbekannt", "X y", category=Category.TERM, today=TODAY),
            Rejection.UNKNOWN_ENTRY,
        )

    def test_target_that_is_itself_a_misheard_word_is_refused(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        self.assertEqual(
            memory.add(
                "Pokahontas", "Mulahn", category=Category.STT, source=Source.MANUAL, today=TODAY
            ),
            Rejection.CHAIN,
        )

    def test_cycles_are_refused(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        self.assertEqual(
            memory.add("Mulan", "Mulahn", category=Category.STT, source=Source.MANUAL, today=TODAY),
            Rejection.CHAIN,
        )

    def test_common_words_become_ambiguous(self):
        self.assertEqual(suggested_category("Mehr"), Category.STT)
        self.assertEqual(suggested_category("Meer"), Category.AMBIGUOUS)
        memory = SpeechMemory()
        entry = memory.add("Tee", "Thee", category=Category.NAME, source=Source.MANUAL, today=TODAY)
        self.assertEqual(entry.category, Category.AMBIGUOUS)

    def test_limit(self):
        memory = SpeechMemory()
        for i in range(MAX_ENTRIES):
            name = "Wort" + "".join(chr(ord("a") + int(d)) for d in f"{i:03d}")
            self.assertIsInstance(
                memory.add(
                    name, name + "x", category=Category.TERM, source=Source.MANUAL, today=TODAY
                ),
                Entry,
            )
        self.assertEqual(
            memory.add(
                "Zusatzwort", "Zusatz", category=Category.TERM, source=Source.MANUAL, today=TODAY
            ),
            Rejection.FULL,
        )

    def test_delete_and_clear(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        self.assertTrue(memory.delete("MULAHN"))
        self.assertFalse(memory.delete("Mulahn"))
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        memory.clear()
        self.assertEqual(len(memory), 0)


class PersistenceContract(unittest.TestCase):
    def test_round_trip_contains_only_pairs(self):
        memory = memory_with(("Mulahn", "Mulan", Category.STT))
        data = memory.export_data()
        self.assertEqual(
            data,
            {
                "entries": [
                    {
                        "heard": "Mulahn",
                        "intended": "Mulan",
                        "category": "stt",
                        "source": "manual",
                        "confirmed_on": TODAY,
                    }
                ]
            },
        )
        self.assertEqual(SpeechMemory(load_entries(data)).export_data(), data)

    def test_missing_data_is_empty(self):
        self.assertEqual(load_entries(None), [])

    def test_damaged_data_fails_closed(self):
        good = {
            "heard": "Mulahn",
            "intended": "Mulan",
            "category": "stt",
            "source": "manual",
            "confirmed_on": TODAY,
        }
        for data in (
            [],
            {"entries": "x"},
            {"entries": [good, "x"]},
            {"entries": [good | {"category": "secret"}]},
            {"entries": [good | {"source": "auto"}]},
            {"entries": [good | {"confirmed_on": "gestern"}]},
            {"entries": [good | {"heard": "Licht"}]},
            {"entries": [good | {"heard": "T"}]},
            {"entries": [good, good | {"intended": "Moulin"}]},
            {"entries": [good] * (MAX_ENTRIES + 1)},
        ):
            with self.subTest(data=str(data)[:60]):
                with self.assertRaises(LoadError):
                    load_entries(data)


class SharedSessionState(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = SessionStore(clock=self.clock)

    def test_proposal_is_single_use_and_session_bound(self):
        self.assertTrue(self.store.set_proposal("a", "Mulahn", "Mulan"))
        self.assertIsNone(self.store.pop_proposal("b"))
        self.assertEqual(self.store.pop_proposal("a"), ("Mulahn", "Mulan"))
        self.assertIsNone(self.store.pop_proposal("a"))

    def test_peek_does_not_consume_and_drop_does_(self):
        self.store.set_proposal("a", "Mulahn", "Mulan")
        for _ in range(3):
            self.assertEqual(
                self.store.peek_proposal("a"), (ProposalStatus.OPEN, ("Mulahn", "Mulan"))
            )
        self.assertEqual(self.store.peek_proposal("b"), (ProposalStatus.NONE, None))
        self.store.drop_proposal("b")  # another session: untouched
        self.assertTrue(self.store.has_proposal("a"))
        self.store.drop_proposal("a")
        self.assertEqual(self.store.peek_proposal("a"), (ProposalStatus.NONE, None))

    def test_peek_reports_expiry_once_and_never_revives(self):
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.clock.now += DIALOGUE_TTL_SECONDS - 1
        self.assertEqual(self.store.peek_proposal("a")[0], ProposalStatus.OPEN)
        self.clock.now += 2
        self.assertEqual(self.store.peek_proposal("a"), (ProposalStatus.EXPIRED, None))
        self.assertEqual(self.store.peek_proposal("a"), (ProposalStatus.NONE, None))

    def test_proposal_expires(self):
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.clock.now += DIALOGUE_TTL_SECONDS + 1
        self.assertIsNone(self.store.pop_proposal("a"))

    def test_no_session_no_proposal(self):
        for cid in (None, "", "   "):
            self.assertFalse(self.store.set_proposal(cid, "Mulahn", "Mulan"))

    def test_open_questions_replace_each_other(self):
        self.store.set_chat_followup("a")
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.assertFalse(self.store.pop_chat_followup("a"))
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.store.set_chat_followup("a")
        self.assertIsNone(self.store.pop_proposal("a"))
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.store.set_clarification("a", ClarificationKind.QUESTION_OR_DEVICE)
        self.assertIsNone(self.store.pop_proposal("a"))

    def test_clear_proposals(self):
        self.store.set_proposal("a", "Mulahn", "Mulan")
        self.store.set_proposal("b", "Pokahontas", "Pocahontas")
        self.store.clear_proposals()
        self.assertIsNone(self.store.pop_proposal("a"))
        self.assertIsNone(self.store.pop_proposal("b"))


if __name__ == "__main__":
    unittest.main()
