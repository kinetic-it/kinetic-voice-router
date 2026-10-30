"""R3.3: Live-Test einer harmlosen Erklaerfrage.

Eine explizite Beschraenkung des Gespraechskanals ist keine erfundene
Home-Assistant-Berechtigungs- oder Statusbehauptung. Der Sicherheitsfilter
muss echte HA-Ausfaelle, fehlende Rechte und ausgedachte Aktionen
weiterhin konservativ zurueckweisen.

Nur synthetische Texte, keine privaten Logs oder Entitaeten.
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

from voice_router import Lane, RouterBridge, responses, simulate  # noqa: E402
from voice_router.errors import normalize_chat_output  # noqa: E402
from voice_router.model import FailureCode  # noqa: E402

QUESTION = "Kannst du mir erklären, wie ich die Lampe einschalten kann?"
EXPLANATION = (
    "Ich habe keinen direkten Zugriff auf die Schalter, deshalb kann ich "
    "die Lampe nicht aus dem Gespräch heraus schalten."
)


class LiveExplanationVsClaims(unittest.TestCase):
    def test_simulation_is_chat_not_action(self):
        result = simulate(QUESTION, "de")
        self.assertIs(result.lane, Lane.CHAT)
        self.assertEqual(result.rule_id, "R-KNOWLEDGE-02")
        self.assertTrue(result.may_call_hermes)

    def test_real_hermes_channel_limit_not_blocked(self):
        self.assertEqual(normalize_chat_output(EXPLANATION), (EXPLANATION, False))

    def test_short_channel_limits_are_not_ha_claims(self):
        for answer in (
            "Ich habe keinen direkten Zugriff auf die Schalter.",
            "Ich kann die Lampe nicht aus dem Gespräch heraus schalten.",
            "Ich kann den Schalter nicht aus dem Gespräch heraus steuern.",
            "Die Steuerung läuft über Home Assistant. "
            "Ich habe keinen direkten Zugriff auf die Schalter.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(normalize_chat_output(answer), (answer, False))

    def test_bridge_delivers_explanation(self):
        async def answer() -> str:
            return EXPLANATION

        bridge = RouterBridge.from_options({"mode": "active"})
        reply = asyncio.run(
            bridge.async_handle(
                text=QUESTION,
                language="de",
                conversation_id="test",
                call_hermes=answer,
                hermes_errors=(),
            )
        )
        self.assertIsNotNone(reply)
        self.assertEqual(reply.text, EXPLANATION)
        self.assertTrue(reply.hermes_called)
        self.assertFalse(reply.is_error)
        self.assertIs(reply.decision.lane, Lane.CHAT)

    def test_disallowed_ha_rights_and_system_failures_still_blocked(self):
        for answer in (
            "Ich habe keinen Zugriff auf Home Assistant.",
            "Ich habe keine Verbindung zu Home Assistant.",
            "Ich habe keinen direkten Zugriff auf die Schalter, "
            "außerdem ist Home Assistant nicht erreichbar.",
            "Ich kann die Lampe nicht aus dem Gespräch heraus schalten, "
            "weil Home Assistant nicht erreichbar ist.",
            "Ich darf deine Geräte nicht schalten.",
            "Leider habe ich keine Berechtigung, die Steckdose zu steuern.",
            "Das Gerät ist nicht freigegeben.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    normalize_chat_output(answer),
                    (responses.UNVERIFIED_SYSTEM_CLAIM, True),
                )

    def test_fake_checks_and_actions_stay_blocked(self):
        self.assertEqual(
            normalize_chat_output("Ich habe die Lampe eingeschaltet."),
            (responses.NOT_EXECUTED, True),
        )
        self.assertEqual(
            normalize_chat_output("Ich habe nachgeschaut: Dein Warp-Antrieb ist aus."),
            (responses.UNVERIFIED_SYSTEM_CLAIM, True),
        )

    def test_normal_educational_answer_kept(self):
        answer = "Du kannst in Home Assistant einen passenden Gerätenamen verwenden."
        self.assertEqual(normalize_chat_output(answer), (answer, False))


# --- R3.3 Review: Gegenproben zum Ausnahmemechanismus (Rest des Satzes bleibt streng) ------------

LIMIT = "Ich habe keinen direkten Zugriff auf die Schalter"
LIMIT_2 = "Ich kann die Lampe nicht aus dem Gespräch heraus schalten"


class ChannelLimitPlusClaim(unittest.TestCase):
    """Die erlaubte Kanalgrenze darf keine zweite Aussage im selben Satz durchschleusen."""

    def test_rights_connection_and_exposure_claims_after_limit_stay_blocked(self):
        for tail in (
            "mir fehlen die Rechte",
            "weil das nicht vorgesehen ist",
            "ich habe keine Berechtigung dafür",
            "weil mir die Rechte verwehrt sind",
            "die Verbindung ist unterbrochen",
            "weil sie nicht freigegeben sind",
            "weil die Freigabe fehlt",
            "weil Home Assistant mir das verwehrt",
            "denn Home Assistant ist nicht erreichbar",
            "ich bin nicht mit dem System verbunden",
            "weil mir der Zugang gesperrt wurde",
        ):
            for limit in (LIMIT, LIMIT_2):
                answer = f"{limit}, {tail}."
                with self.subTest(answer=answer):
                    self.assertEqual(
                        normalize_chat_output(answer), (responses.UNVERIFIED_SYSTEM_CLAIM, True)
                    )

    def test_claim_before_limit_stays_blocked(self):
        for answer in (
            f"Home Assistant ist nicht erreichbar, {LIMIT.lower()}.",
            f"Mir fehlen die Rechte, deshalb {LIMIT_2[0].lower() + LIMIT_2[1:]}.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    normalize_chat_output(answer), (responses.UNVERIFIED_SYSTEM_CLAIM, True)
                )

    def test_limit_with_harmless_continuation_is_kept(self):
        for answer in (
            f"{LIMIT}, deshalb {LIMIT_2[0].lower() + LIMIT_2[1:]}.",
            f"{LIMIT}, aber du kannst den Schalter selbst bedienen.",
            f"{LIMIT}, aber du kannst sie selbst schalten.",
            f"Leider {LIMIT[0].lower() + LIMIT[1:]}.",
            f"{LIMIT_2}, aber du kannst es mir im Befehl sagen.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(normalize_chat_output(answer), (answer, False))

    def test_wider_phrasings_are_not_exempted(self):
        # Bewusst eng: andere Formulierungen und Objekte gehen durch die strenge Pruefung.
        for answer in (
            "Ich habe keinen direkten Zugriff auf deine Geräte.",
            "Ich habe keinen Zugriff auf die Lampe.",
            "Ich habe keinen direkten Zugriff auf Home Assistant.",
            "Ich kann Geräte nicht aus dem Gespräch heraus schalten, weil Home Assistant fehlt.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    normalize_chat_output(answer), (responses.UNVERIFIED_SYSTEM_CLAIM, True)
                )

    def test_limit_never_hides_action_or_check_claims(self):
        for answer in (
            f"{LIMIT}, aber ich habe die Lampe gerade eingeschaltet.",
            f"{LIMIT_2}. Ich habe die Lampe gerade eingeschaltet.",
            f"{LIMIT}. Ich habe nachgeschaut: Dein Warp-Antrieb ist aus.",
            f"{LIMIT}. Die Lampe ist jetzt an.",
        ):
            with self.subTest(answer=answer):
                text, replaced = normalize_chat_output(answer)
                self.assertTrue(replaced)
                self.assertIn(text, (responses.NOT_EXECUTED, responses.UNVERIFIED_SYSTEM_CLAIM))


# --- R3.3 Review: lange Antworten sind sprechbar oder ehrlich abgelehnt -----------------------

LONG_EXPLANATION = (
    "Du kannst die Lampe z. B. mit dem Befehl Schalte die Lampe ein steuern, wenn sie in Assist "
    "freigegeben ist. Ich habe keinen direkten Zugriff auf die Schalter, deshalb kann ich die "
    "Lampe nicht aus dem Gespräch heraus schalten. "
    "Weitere Hinweise findest du in den Einstellungen unter Sprachassistenten. " * 3
)


class SpokenLength(unittest.TestCase):
    def test_abbreviations_do_not_end_a_sentence(self):
        text = (
            "Du kannst die Lampe z. B. per App einschalten. Alternativ nutzt du den Wandschalter."
        )
        text += " Weitere Hinweise folgen hier." * 12
        spoken, replaced = normalize_chat_output(text)
        self.assertTrue(replaced)
        self.assertEqual(
            spoken,
            "Du kannst die Lampe z. B. per App einschalten. Alternativ nutzt du den Wandschalter.",
        )

    def test_numbered_steps_are_not_cut_after_the_number(self):
        text = "So geht's: 1. Öffne die App. 2. Tippe auf die Lampe. " + "Danach wartest du. " * 20
        spoken, replaced = normalize_chat_output(text)
        self.assertTrue(replaced)
        self.assertEqual(spoken, "So geht's: 1. Öffne die App. 2. Tippe auf die Lampe.")

    def test_spoken_part_never_ends_inside_an_abbreviation(self):
        for text in (
            "Beispiele gibt es viele, z. B. " + "weitere Beispiele " * 30 + "folgen.",
            "Das gilt u. a. " + "für viele Geräte " * 30 + "im Haus.",
        ):
            with self.subTest(text=text[:20]):
                spoken, replaced = normalize_chat_output(text)
                self.assertTrue(replaced)
                self.assertEqual(spoken, responses.TOO_LONG_TO_SPEAK)

    def test_overlong_single_sentence_gets_honest_reason_not_a_fake_error(self):
        spoken, replaced = normalize_chat_output("Erklärung " * 60 + "Ende.")
        self.assertTrue(replaced)
        self.assertEqual(spoken, responses.TOO_LONG_TO_SPEAK)
        self.assertNotEqual(spoken, responses.FAILURE_TEXT[FailureCode.UNKNOWN_FAILURE])
        self.assertLessEqual(len(spoken), 100)
        self.assertNotIn("Home Assistant", spoken)

    def test_long_live_like_answer_keeps_useful_first_sentences_and_stays_bounded(self):
        spoken, replaced = normalize_chat_output(LONG_EXPLANATION)
        self.assertTrue(replaced)
        self.assertTrue(spoken.startswith("Du kannst die Lampe z. B. mit dem Befehl"))
        self.assertLessEqual(len(spoken), 320)
        self.assertRegex(spoken, r"[.!?]$")

    def test_long_answer_with_later_bad_claim_is_still_blocked(self):
        # Konservativ: geprueft wird die ganze Antwort, nicht nur der gesprochene Teil.
        text = LONG_EXPLANATION + " Ich habe keine Verbindung zu Home Assistant."
        self.assertEqual(normalize_chat_output(text), (responses.UNVERIFIED_SYSTEM_CLAIM, True))

    def test_bridge_speaks_bounded_explanation_and_counts_hermes_ok(self):
        async def answer() -> str:
            return LONG_EXPLANATION

        bridge = RouterBridge.from_options({"mode": "active"})
        reply = asyncio.run(
            bridge.async_handle(
                text=QUESTION,
                language="de",
                conversation_id="test",
                call_hermes=answer,
                hermes_errors=(),
            )
        )
        self.assertFalse(reply.is_error)
        self.assertLessEqual(len(reply.text), 320)
        self.assertTrue(reply.text.startswith("Du kannst die Lampe z. B."))
        self.assertEqual(bridge.stats.snapshot()["hermes_results"]["ok"], 1)

    def test_bridge_with_blocked_claim_keeps_neutral_answer_and_no_action_flag(self):
        async def answer() -> str:
            return f"{LIMIT}, mir fehlen die Rechte."

        bridge = RouterBridge.from_options({"mode": "active"})
        reply = asyncio.run(
            bridge.async_handle(
                text=QUESTION,
                language="de",
                conversation_id="test",
                call_hermes=answer,
                hermes_errors=(),
            )
        )
        self.assertEqual(reply.text, responses.UNVERIFIED_SYSTEM_CLAIM)
        self.assertFalse(reply.decision.may_call_ha_action)


if __name__ == "__main__":
    unittest.main()
