"""R3.2-Befunde (Live-Fehler und Codeaudit) mit Gegenproben.

Jeder Abschnitt hat positive Faelle und negative Gegenproben. Reiner Router-Kern,
Standardbibliothek, keine HA-Instanz.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import unittest
from unittest import mock

ROUTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "custom_components" / "kinetic_voice_router"
)
sys.path.insert(0, str(ROUTER_DIR))

from voice_router import Lane, RouterBridge, responses, simulate  # noqa: E402
from voice_router import adapter as adapter_module  # noqa: E402
from voice_router.classify import is_narrative_request  # noqa: E402
from voice_router.errors import normalize_chat_output  # noqa: E402
from voice_router.model import FailureCode  # noqa: E402

# --- Befund 2: Statusfrage zu eigenem, unbekanntem Gegenstand --------------------------------

LIVE_REPRO = "Ist mein imaginärer Warp-Antrieb eingeschaltet?"
PRIVATE_STATUS = [
    LIVE_REPRO,
    "Ist mein Warp Antrieb an?",
    "Ist mein Handy online?",
    "Ist unsere unbekannte Anlage eingeschaltet?",
    # STT-Varianten: klein, ohne Satzzeichen, zusammengeschrieben, Fuellwort
    "ist mein imaginärer warp antrieb eingeschaltet",
    "ist mein warpantrieb an",
    "Okay Nabu, ist mein Warp-Antrieb aus?",
    "Ist meine Spielkonsole offline?",
    "Sind unsere Server online?",
    "Sag mir, ob mein Warp-Antrieb an ist",
]
PRIVATE_STATUS_NEGATIVES = [
    "Was ist ein Warp-Antrieb?",
    "Erzähl mir eine Geschichte über einen Warp-Antrieb",
    "Ist ein Warp-Antrieb in Star Trek real?",
    "Wie schaltet man einen Warp-Antrieb ein?",
    "Ist unser Bäcker heute offen?",
    "Ist mein Vortrag gut angekommen?",
    "Ist meine Frage zu lang?",
    "Ist mein Deutsch gut genug?",
    "Ist mein Urlaub schon vorbei?",
    "Ist das Konzert schon aus?",
]


def run(coro):
    return asyncio.run(coro)


async def _never_hermes() -> str:
    raise AssertionError("Hermes darf nicht gerufen werden")


class PrivateDeviceStatus(unittest.TestCase):
    def test_live_repro_and_variants_are_status_fallback(self):
        for text in PRIVATE_STATUS:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CONTROL_FALLBACK)
                self.assertEqual(decision.rule_id, "R-STATUS-01")
                self.assertEqual(decision.response, responses.STATUS_NOT_AVAILABLE)
                self.assertFalse(decision.may_call_hermes)
                self.assertFalse(decision.may_call_ha_action)

    def test_knowledge_and_fiction_still_reach_hermes(self):
        for text in PRIVATE_STATUS_NEGATIVES:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CHAT)
                self.assertTrue(decision.may_call_hermes)

    def test_active_mode_answers_without_hermes(self):
        bridge = RouterBridge.from_options({"mode": "active"})
        reply = run(
            bridge.async_handle(
                text=LIVE_REPRO,
                language="de",
                conversation_id="c",
                call_hermes=_never_hermes,
                hermes_errors=(),
            )
        )
        self.assertEqual(reply.text, responses.STATUS_NOT_AVAILABLE)
        self.assertFalse(reply.is_error)
        self.assertFalse(reply.hermes_called)
        self.assertEqual(bridge.stats.snapshot()["decisions"]["active"]["CONTROL_FALLBACK"], 1)
        self.assertNotIn("warp", repr(reply.decision.trace()).lower())

    def test_observe_counts_status_without_state(self):
        bridge = RouterBridge.from_options({"mode": "observe"})
        bridge.observe(text=LIVE_REPRO, language="de")
        self.assertEqual(bridge.stats.snapshot()["decisions"]["observe"]["CONTROL_FALLBACK"], 1)
        self.assertEqual(bridge.store._entries, {})

    def test_off_mode_unchanged(self):
        bridge = RouterBridge.from_options({"mode": "off"})
        self.assertIsNone(
            run(
                bridge.async_handle(
                    text=LIVE_REPRO,
                    language="de",
                    conversation_id="c",
                    call_hermes=_never_hermes,
                    hermes_errors=(),
                )
            )
        )


# --- Befund 3 P1: eingebettete Erklaerfrage ist keine Aufforderung ----------------------------

EXPLAIN_QUESTIONS = [
    "Kannst du mir erklären, wie ich die Lampe einschalten kann?",
    "Ich möchte wissen, wie man eine Lampe einschalten kann.",
    "Kannst du erklären, warum man die Heizung ausschalten sollte?",
    "Kannst du mir zeigen, wie man das Licht dimmen kann?",
    "Könntest du mir sagen, wann man die Heizung abschalten sollte?",
]
EXPLAIN_NEGATIVES = [
    "Kannst du die Lampe einschalten?",
    "Kannst du mal das Licht ausmachen",
    "Ich möchte das Licht einschalten",
    "Kannst du mir sagen, wie spät es ist, und das Licht einschalten?",
]


class EmbeddedExplanation(unittest.TestCase):
    def test_explanations_reach_hermes(self):
        for text in EXPLAIN_QUESTIONS:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CHAT)
                self.assertTrue(decision.may_call_hermes)

    def test_requests_stay_control_fallback(self):
        for text in EXPLAIN_NEGATIVES:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CONTROL_FALLBACK)
                self.assertFalse(decision.may_call_hermes)

    def test_how_question_unchanged(self):
        self.assertEqual(simulate("Wie schalte ich die Lampe ein?", "de").rule_id, "R-KNOWLEDGE-01")


# --- Befund 3 P1: Aussagen mit an/aus sind keine Kurzbefehle -----------------------------------

STATEMENTS = [
    "Ich fange morgen an.",
    "Das Licht geht aus.",
    "Der Film fängt an",
    "Morgen fange ich an",
    "Gleich geht es los und wir fangen an",
]
SHORT_COMMANDS = [
    "Licht aus",
    "Das Wohnzimmerlicht bitte aus",
    "Schalte das Licht aus",
    "Alles aus",
    "Küche Licht aus",
    "Rollos runter",
]


class StatementsVsShortCommands(unittest.TestCase):
    def test_statements_are_not_commands(self):
        for text in STATEMENTS:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertNotEqual(decision.rule_id, "R-ACTION-01")
                self.assertIsNot(decision.lane, Lane.CONTROL_FALLBACK)

    def test_short_commands_unchanged(self):
        for text in SHORT_COMMANDS:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertIs(decision.lane, Lane.CONTROL_FALLBACK)
                self.assertEqual(decision.response, responses.NOT_EXECUTED)


# --- Befund 3 P1: interner Routerfehler im Modus Aktiv ist fail-closed -------------------------


class RouterFailureFailClosed(unittest.TestCase):
    def _handle(self, bridge, call_hermes=_never_hermes):
        return run(
            bridge.async_handle(
                text="Erzähl mir etwas über die Alpen",
                language="de",
                conversation_id="c",
                call_hermes=call_hermes,
                hermes_errors=(ValueError,),
            )
        )

    def test_route_exception_gives_neutral_error_without_hermes(self):
        bridge = RouterBridge.from_options({"mode": "active"})
        with mock.patch.object(adapter_module, "route", side_effect=RuntimeError("boom")):
            reply = self._handle(bridge)
        self.assertTrue(reply.is_error)
        self.assertFalse(reply.hermes_called)
        self.assertEqual(reply.text, responses.LIVE_FAILURE_TEXT[FailureCode.UNKNOWN_FAILURE])
        self.assertEqual(reply.decision.rule_id, "R-GUARD-ERROR")
        self.assertFalse(reply.decision.may_call_hermes)
        self.assertFalse(reply.decision.may_call_ha_action)
        self.assertEqual(bridge.stats.snapshot()["router_errors"], 1)

    def test_broken_statistics_also_fail_closed(self):
        bridge = RouterBridge.from_options({"mode": "active"})
        bridge.stats = mock.Mock(side_effect=None)
        bridge.stats.record_decision.side_effect = RuntimeError("stats")
        bridge.stats.record_router_error.side_effect = RuntimeError("stats")
        reply = self._handle(bridge)
        self.assertTrue(reply.is_error)
        self.assertFalse(reply.hermes_called)

    def test_off_and_observe_never_reach_router_logic(self):
        for mode in ("off", "observe"):
            bridge = RouterBridge.from_options({"mode": mode})
            with mock.patch.object(adapter_module, "route", side_effect=RuntimeError("boom")):
                self.assertIsNone(self._handle(bridge))
            self.assertEqual(bridge.stats.snapshot()["router_errors"], 0)

    def test_hermes_failures_keep_their_classification(self):
        async def failing() -> str:
            raise ValueError("x")

        bridge = RouterBridge.from_options({"mode": "active"})
        reply = self._handle(bridge, failing)
        self.assertTrue(reply.hermes_called)
        self.assertEqual(reply.text, responses.LIVE_FAILURE_TEXT[FailureCode.UNKNOWN_FAILURE])
        self.assertEqual(bridge.stats.snapshot()["router_errors"], 0)
        self.assertEqual(bridge.stats.snapshot()["hermes_results"]["UNKNOWN_FAILURE"], 1)

    def test_working_router_still_forwards_chat(self):
        async def hermes() -> str:
            return "Die Alpen sind ein Hochgebirge."

        reply = self._handle(RouterBridge.from_options({"mode": "active"}), hermes)
        self.assertEqual(reply.text, "Die Alpen sind ein Hochgebirge.")
        self.assertTrue(reply.hermes_called)


# --- Befund 3 P2: Ausgabefilter --------------------------------------------------

STORY = "Es war einmal eine kleine Lampe. Das Licht ist jetzt an, sagte das Kind."


class ChatOutputFilter(unittest.TestCase):
    def test_story_keeps_narrative_state_sentence(self):
        self.assertEqual(normalize_chat_output(STORY, narrative=True), (STORY, False))

    def test_without_story_request_claim_is_still_replaced(self):
        self.assertEqual(normalize_chat_output(STORY), (responses.NOT_EXECUTED, True))

    def test_story_never_exempts_first_person_claims(self):
        for text in (
            "Ich habe das Licht eingeschaltet.",
            "Erledigt.",
            "Ich schalte jetzt die Lampe an.",
            "Es war einmal eine Lampe. Ich habe sie gerade eingeschaltet.",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    normalize_chat_output(text, narrative=True), (responses.NOT_EXECUTED, True)
                )

    def test_claimed_device_check_is_replaced(self):
        for text in (
            "Ich habe nachgeschaut: Dein Warp-Antrieb ist aus.",
            "Hab ich gerade geprüft, dein Handy ist online!",
            "Keine Sorge, ich habe nachgesehen. Der Warp-Antrieb ist ausgeschaltet.",
        ):
            for narrative in (False, True):
                with self.subTest(text=text, narrative=narrative):
                    self.assertEqual(
                        normalize_chat_output(text, narrative=narrative),
                        (responses.UNVERIFIED_SYSTEM_CLAIM, True),
                    )

    def test_humour_and_research_answers_kept(self):
        for text in (
            "Ich habe nachgeschaut, die Alpen sind rund 1200 Kilometer lang.",
            "Ich habe nachgeschaut, das ist zu weit für einen Tagesausflug.",
            "Ich habe nachgeschaut, das Museum ist an Feiertagen offen.",
            "Ein Warp-Antrieb krümmt den Raum. Leider ist meiner gerade in Reparatur.",
            "Haha, dein imaginärer Warp-Antrieb läuft bestimmt mit Fantasie-Energie.",
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_chat_output(text), (text, False))

    def test_narrative_request_detection(self):
        for text in (
            "Erzähl mir eine kurze Geschichte über eine Lampe",
            "Bitte schreib ein Gedicht über das Licht",
            "Denk dir ein Märchen aus",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_narrative_request(text))
        for text in (
            "Erzähl mir, wie eine Steckdose funktioniert",
            "Schalte das Licht an",
            "Ist die Geschichte wahr?",
            None,
            42,
        ):
            with self.subTest(text=text):
                self.assertFalse(is_narrative_request(text))

    def test_bridge_uses_story_context(self):
        async def story() -> str:
            return STORY

        for request, expected in (
            ("Erzähl mir eine kurze Geschichte über eine Lampe", STORY),
            ("Erzähl mir etwas über Lampen", responses.NOT_EXECUTED),
        ):
            with self.subTest(request=request):
                reply = run(
                    RouterBridge.from_options({"mode": "active"}).async_handle(
                        text=request,
                        language="de",
                        conversation_id="c",
                        call_hermes=story,
                        hermes_errors=(),
                    )
                )
                self.assertEqual(reply.text, expected)


class Invariants(unittest.TestCase):
    def test_no_new_sentence_enables_actions(self):
        corpus = (
            PRIVATE_STATUS
            + PRIVATE_STATUS_NEGATIVES
            + EXPLAIN_QUESTIONS
            + EXPLAIN_NEGATIVES
            + STATEMENTS
            + SHORT_COMMANDS
        )
        for text in corpus:
            with self.subTest(text=text):
                decision = simulate(text, "de")
                self.assertFalse(decision.may_call_ha_action)
                trace = repr(decision.trace()).lower()
                self.assertNotIn(text.lower(), trace)


if __name__ == "__main__":
    unittest.main()
