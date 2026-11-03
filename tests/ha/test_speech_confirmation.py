"""ASM learning confirmation: the proposal is consumed only by a valid, unambiguous answer.

Regression for the beta v0.5.0b3 report "Ja" -> "Das habe ich nicht verstanden." with an
empty lexicon: the open proposal used to be popped BEFORE the ChatLog context was
validated, so a "Ja" in a wrong or incomplete context destroyed it.

Real conversation entity, router and HermesClient against the local fake companion;
Home Assistant parts are contract stubs (see conftest.py). Synthetic data only.
"""

from __future__ import annotations

import logging

from conftest import AssistantContent, ChatLog, SystemContent, UserContent
from test_speech_memory import ASK, CORRECT, PROPOSAL, load, say, stored_pairs

from custom_components.kinetic_voice_router.voice_router import responses

AGENT = "conversation.kinetic_voice_router"
LEARNED = "Gemerkt: Mit „Mulahn“ meinst du „Mulan“."


async def ask_proposal(
    entity,
    companion,
    cid: str = "s1",
    *,
    ask: str = ASK,
    correct: str = CORRECT,
    question: str = PROPOSAL,
) -> ChatLog:
    """Run the first two turns; the returned ChatLog ends with the learning question."""
    companion.answers = ["Das kenne ich nicht.", "Das ist ein Disney-Film.", "Gern."]
    log = ChatLog(conversation_id=cid)
    await say(entity, ask, log)
    proposed = await say(entity, correct, log)
    assert proposed.response.speech.endswith(question)
    return log


# --- the reported defect ---------------------------------------------------------------


async def test_wrong_context_does_not_burn_the_proposal(hass, companion):
    """Red before the fix: a first "Ja" without the previous assistant turn killed the proposal."""
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)

    # same conversation ID, but HA supplied no previous assistant turn
    incomplete = ChatLog(conversation_id="s1")
    first = await say(entity, "Ja", incomplete)
    assert first.response.speech == responses.NOT_UNDERSTOOD
    assert stored_pairs(hass) == []

    # the genuine answer within the window still works
    learned = await say(entity, "Ja", log)
    assert learned.response.speech == LEARNED
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]


async def test_foreign_agent_turn_does_not_confirm_and_does_not_burn(hass, companion):
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    foreign = ChatLog(
        [
            SystemContent(""),
            UserContent("Mach das Licht an"),
            AssistantContent("conversation.home_assistant", "Okay."),
        ],
        conversation_id="s1",
    )
    result = await say(entity, "Ja", foreign)
    assert result.response.speech == responses.NOT_UNDERSTOOD
    assert stored_pairs(hass) == []
    assert (await say(entity, "Ja", log)).response.speech == LEARNED


async def test_unrelated_previous_assistant_turn_does_not_confirm(hass, companion):
    """Red before the fix: any previous assistant turn of this agent was accepted as context."""
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    other_topic = ChatLog(
        [
            SystemContent(""),
            UserContent("Wie spät ist es?"),
            AssistantContent(AGENT, "Es ist Mittag."),
        ],
        conversation_id="s1",
    )
    result = await say(entity, "Ja", other_topic)
    assert result.response.speech != LEARNED
    assert stored_pairs(hass) == []
    assert (await say(entity, "Ja", log)).response.speech == LEARNED
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]


async def test_empty_or_missing_chat_log_never_confirms(hass, companion):
    _, entity = await load(hass)
    await ask_proposal(entity, companion)
    assert (await say(entity, "Ja", ChatLog([], conversation_id="s1"))).response.speech != LEARNED
    assert stored_pairs(hass) == []


# --- valid answers ---------------------------------------------------------------------


async def test_yes_stores_exactly_one_correct_entry(hass, companion):
    entry, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    calls = len(companion.inference_bodies)

    assert (await say(entity, "Ja.", log)).response.speech == LEARNED
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]
    assert len(entry.runtime_data.speech.memory.entries()) == 1
    assert len(companion.inference_bodies) == calls  # the "Ja" is not forwarded to Hermes

    # the proposal is single-use: a second "Ja" adds nothing
    again = await say(entity, "Ja", log)
    assert again.response.speech != LEARNED
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]


async def test_no_stores_nothing_and_the_proposal_is_gone(hass, companion):
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    assert (await say(entity, "Nein.", log)).response.speech == responses.ASM_NOT_LEARNED
    assert (await say(entity, "Ja", log)).response.speech != LEARNED
    assert stored_pairs(hass) == []


async def test_window_is_still_sixty_seconds(hass, companion):
    entry, entity = await load(hass)
    clock = [9000.0]
    entry.runtime_data.bridge.store._clock = lambda: clock[0]

    log = await ask_proposal(entity, companion, "in-time")
    clock[0] += 59
    assert (await say(entity, "Ja", log)).response.speech == LEARNED

    clock[0] = 20000.0
    late_log = await ask_proposal(
        entity,
        companion,
        "too-late",
        ask="Erzähl mir etwas über Pokahontas",
        correct="Nein, ich meinte Pocahontas.",
        question="Soll ich mir merken, dass mit „Pokahontas“ „Pocahontas“ gemeint ist?",
    )
    clock[0] += 61
    assert (await say(entity, "Ja", late_log)).response.speech == responses.NOT_UNDERSTOOD
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]  # only the in-time one


# --- ambiguous and other answers -------------------------------------------------------


async def test_ambiguous_confirmation_stores_nothing_and_lapses(hass, companion):
    entry, entity = await load(hass)
    for ambiguous in ("Ja, mach das", "Ja nein", "Vielleicht", "Ja oder nein"):
        log = await ask_proposal(entity, companion, f"amb-{ambiguous}")
        result = await say(entity, ambiguous, log)
        assert result.response.speech != LEARNED, ambiguous
        assert stored_pairs(hass) == [], ambiguous
        # an unconfirmed proposal is consumed and does not linger for a later "Ja"
        assert not entry.runtime_data.bridge.store.has_proposal(f"amb-{ambiguous}"), ambiguous
        assert (await say(entity, "Ja", log)).response.speech != LEARNED, ambiguous
        assert stored_pairs(hass) == [], ambiguous


async def test_control_command_is_never_taken_as_confirmation(hass, companion):
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    calls = len(companion.inference_bodies)
    result = await say(entity, "Schalte das Licht im Wohnzimmer an", log)
    assert result.response.speech != LEARNED
    assert len(companion.inference_bodies) == calls  # device requests never reach Hermes
    assert stored_pairs(hass) == []
    assert (await say(entity, "Ja", log)).response.speech != LEARNED
    assert stored_pairs(hass) == []


async def test_yes_alone_without_any_proposal_is_not_special(hass, companion):
    _, entity = await load(hass)
    result = await say(entity, "Ja", ChatLog(conversation_id="plain"))
    assert result.response.speech == responses.NOT_UNDERSTOOD
    assert stored_pairs(hass) == []


# --- concurrent conversations ----------------------------------------------------------


async def test_two_active_conversations_do_not_mix(hass, companion):
    entry, entity = await load(hass)
    companion.answers = [
        "Mulahn kenne ich nicht.",  # A: first turn
        "Pokahontas kenne ich nicht.",  # B: first turn
        "Mulan ist ein Disney-Film.",  # A: corrected
        "Pocahontas ist ein Disney-Film.",  # B: corrected
    ]
    log_a, log_b = ChatLog(conversation_id="a"), ChatLog(conversation_id="b")
    await say(entity, ASK, log_a)
    await say(entity, "Erzähl mir etwas über Pokahontas", log_b)
    a = await say(entity, CORRECT, log_a)
    b = await say(entity, "Nein, ich meinte Pocahontas.", log_b)
    assert "„Mulahn“ „Mulan“" in a.response.speech
    assert "„Pokahontas“ „Pocahontas“" in b.response.speech

    # B answers first: only B's pair is stored
    assert (await say(entity, "Ja", log_b)).response.speech.startswith("Gemerkt")
    assert stored_pairs(hass) == [("Pokahontas", "Pocahontas")]

    # a "Nein" in B must not touch A's open proposal; A's "Ja" then stores A's pair
    assert (await say(entity, "Nein", log_b)).response.speech != LEARNED
    assert (await say(entity, "Ja", log_a)).response.speech == LEARNED
    assert sorted(stored_pairs(hass)) == [("Mulahn", "Mulan"), ("Pokahontas", "Pocahontas")]
    assert len(entry.runtime_data.speech.memory.entries()) == 2


# --- privacy and diagnosis -------------------------------------------------------------


async def test_outcome_is_logged_as_code_without_spoken_text(hass, companion, caplog):
    _, entity = await load(hass)
    log = await ask_proposal(entity, companion)
    caplog.set_level(logging.DEBUG, logger="custom_components.kinetic_voice_router")

    await say(entity, "Ja", ChatLog(conversation_id="s1"))  # context invalid
    await say(entity, "Ja", log)  # stored

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "asm_confirmation=context_invalid" in messages
    assert "asm_confirmation=stored" in messages
    for secret in ("Mulahn", "Mulan", "Ja"):
        assert secret not in messages.replace("asm_confirmation", "")


async def test_expired_outcome_is_logged(hass, companion, caplog):
    entry, entity = await load(hass)
    clock = [1000.0]
    entry.runtime_data.bridge.store._clock = lambda: clock[0]
    log = await ask_proposal(entity, companion)
    caplog.set_level(logging.DEBUG, logger="custom_components.kinetic_voice_router")
    clock[0] += 61
    await say(entity, "Ja", log)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "asm_confirmation=expired" in messages
