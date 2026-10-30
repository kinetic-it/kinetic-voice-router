"""The conversation agent: modes, router policy, Hermes errors, session handling.

Runs the real entity, router and HermesClient against a local fake companion.
"""

from __future__ import annotations

import logging

import pytest
from conftest import (
    TOKEN,
    ChatLog,
    ConfigEntry,
    ConversationInput,
    FakeCompanion,
    FakeHass,
    IntentResponseErrorCode,
)

from custom_components.kinetic_voice_router import runtime_stats
from custom_components.kinetic_voice_router.const import (
    CONF_MODE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
)
from custom_components.kinetic_voice_router.voice_router import ClarificationKind, FailureCode, responses

WARP = "Ist mein imaginärer Warp-Antrieb eingeschaltet?"
EXPLAIN = "Kannst du mir erklären, wie ich die Lampe einschalten kann?"
KNOWLEDGE = "Erzähl mir etwas über die Alpen"
CLAIM_ANSWER = "Ich habe das Licht eingeschaltet."
FAILED = "Hermes Agent could not process the request."


async def load(hass: FakeHass, mode: str):
    entry = hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            data={CONF_URL: hass.companion.base_url, CONF_TOKEN: TOKEN, CONF_VERIFY_TLS: True},
            options={CONF_MODE: mode},
            minor_version=3,
        )
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry, hass.entities[entry.entry_id][0]


async def ask(entity, text: str, *, cid: str | None = None, language: str = "de", log=None):
    log = log or ChatLog(conversation_id=cid or "session-1")
    return await entity.async_process(ConversationInput(text, cid, language), log)


def inference_calls(companion: FakeCompanion) -> int:
    return len(companion.inference_bodies)


# --- Conversation language compatibility ---------------------------------------------------


@pytest.mark.parametrize(
    ("advertised", "expected"),
    [
        (["*"], "*"),  # real Hermes Companion: all languages via wildcard list
        (["*", "de"], "*"),
        (["de", "en"], ["de", "en"]),
        ([], "*"),
    ],
)
async def test_supported_languages_normalizes_companion_wildcard(
    hass, companion, advertised, expected
):
    companion.languages = advertised
    entry, entity = await load(hass, "off")
    assert entry.runtime_data.connection.languages == tuple(advertised)
    assert entity.supported_languages == expected


# --- Mode OFF: plain pass-through -----------------------------------------------------------


async def test_off_passes_every_sentence_to_hermes_unchanged(hass, companion):
    _, entity = await load(hass, "off")
    for text in (WARP, EXPLAIN, KNOWLEDGE, "Schalte das Licht aus", "Licht"):
        companion.answers = [CLAIM_ANSWER]  # even an answer the active router would replace
        result = await ask(entity, text)
        assert result.response.speech == CLAIM_ANSWER
        assert result.response.error_code is None
    assert inference_calls(companion) == 5
    assert runtime_stats(hass).snapshot()["decisions"]["active"] == dict.fromkeys(
        runtime_stats(hass).snapshot()["decisions"]["active"], 0
    )


async def test_off_long_answers_are_not_cut(hass, companion):
    _, entity = await load(hass, "off")
    companion.answers = ["Ein langer Satz. " * 60]
    result = await ask(entity, KNOWLEDGE)
    assert result.response.speech == ("Ein langer Satz. " * 60).strip()


# --- Mode OBSERVE: count only -----------------------------------------------------------------


async def test_observe_counts_but_never_changes_the_turn(hass, companion):
    entry, entity = await load(hass, "observe")
    companion.answers = [CLAIM_ANSWER]
    result = await ask(entity, WARP)
    assert result.response.speech == CLAIM_ANSWER  # not replaced by the router
    assert inference_calls(companion) == 1  # Hermes was asked although the router would answer
    snap = runtime_stats(hass).snapshot()["decisions"]["observe"]
    assert snap["CONTROL_FALLBACK"] == 1
    assert sum(snap.values()) == 1
    assert entry.runtime_data.bridge.store._entries == {}  # no session state, no IDs


async def test_observe_and_off_send_identical_requests(hass, companion):
    _, observe_entity = await load(hass, "observe")
    await ask(observe_entity, EXPLAIN, cid="same")
    observed = list(companion.inference_bodies)
    await hass.config_entries.async_unload("kvr-1")
    hass.config_entries._entries.clear()
    companion.inference_bodies.clear()
    _, off_entity = await load(hass, "off")
    await ask(off_entity, EXPLAIN, cid="same")
    assert companion.inference_bodies == observed


async def test_observe_failure_does_not_break_the_turn(hass, companion, monkeypatch):
    entry, entity = await load(hass, "observe")

    def broken(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(entry.runtime_data.bridge, "observe", broken)
    result = await ask(entity, KNOWLEDGE)
    assert result.response.speech == "Die Alpen sind ein Hochgebirge."


@pytest.mark.parametrize("mode", ["off", "observe"])
async def test_off_and_observe_never_let_the_router_decide(hass, companion, mode, monkeypatch):
    """Not only the router's own guard: the agent must not even ask it to handle the turn."""
    entry, entity = await load(hass, mode)

    async def forbidden(**kwargs):
        raise AssertionError("router.async_handle must not be called outside mode ACTIVE")

    monkeypatch.setattr(entry.runtime_data.bridge, "async_handle", forbidden)
    companion.answers = [CLAIM_ANSWER]
    result = await ask(entity, WARP)
    assert result.response.speech == CLAIM_ANSWER


# --- Mode ACTIVE ------------------------------------------------------------------------------


async def test_active_status_of_unknown_device_is_answered_without_hermes(hass, companion):
    _, entity = await load(hass, "active")
    result = await ask(entity, WARP)
    assert result.response.speech == responses.STATUS_NOT_AVAILABLE
    assert result.response.error_code is None
    assert inference_calls(companion) == 0
    assert companion.requests[-1]["path"] != "/v1/inference"


async def test_active_explanation_reaches_hermes_and_the_honest_limit_is_kept(hass, companion):
    _, entity = await load(hass, "active")
    answer = (
        "Ich habe keinen direkten Zugriff auf die Schalter, deshalb kann ich "
        "die Lampe nicht aus dem Gespräch heraus schalten."
    )
    companion.answers = [answer]
    result = await ask(entity, EXPLAIN)
    assert result.response.speech == answer
    assert inference_calls(companion) == 1


@pytest.mark.parametrize(
    ("answer", "replacement"),
    [
        (CLAIM_ANSWER, responses.NOT_EXECUTED),
        ("Ich habe nachgeschaut: Dein Warp-Antrieb ist aus.", responses.UNVERIFIED_SYSTEM_CLAIM),
        ("Home Assistant ist leider nicht erreichbar.", responses.UNVERIFIED_SYSTEM_CLAIM),
        (
            "Ich habe keinen direkten Zugriff auf die Schalter, mir fehlen die Rechte.",
            responses.UNVERIFIED_SYSTEM_CLAIM,
        ),
    ],
)
async def test_active_replaces_unverified_claims(hass, companion, answer, replacement):
    _, entity = await load(hass, "active")
    companion.answers = [answer]
    result = await ask(entity, KNOWLEDGE)
    assert result.response.speech == replacement


async def test_active_device_command_is_not_executed_and_not_forwarded(hass, companion):
    _, entity = await load(hass, "active")
    result = await ask(entity, "Schalte das Licht im Flur aus")
    assert result.response.speech == responses.NOT_EXECUTED
    assert inference_calls(companion) == 0
    assert not hasattr(hass, "service_calls")


async def test_active_bare_yes_is_never_an_approval(hass, companion):
    _, entity = await load(hass, "active")
    await ask(entity, "Licht", cid="c1")  # clarification pending
    result = await ask(entity, "Ja", cid="c1")
    assert result.response.speech == responses.CONFIRMATION_NOT_EXECUTABLE
    assert inference_calls(companion) == 0


async def test_active_sessions_are_isolated(hass, companion):
    _, entity = await load(hass, "active")
    await ask(entity, "Schalte das Licht aus", cid="a")  # records a failure for session a
    other = await ask(entity, "Warum ging das nicht?", cid="b")
    assert other.response.speech == responses.NO_SAFE_REASON  # nothing leaks from session a
    same = await ask(entity, "Warum ging das nicht?", cid="a")
    assert same.response.speech == responses.FAILURE_TEXT[FailureCode.ACTION_LIKE_UNHANDLED]


async def test_active_replay_of_the_same_sentence_is_stable(hass, companion):
    entry, entity = await load(hass, "active")
    results = [(await ask(entity, WARP, cid="r")).response.speech for _ in range(25)]
    assert set(results) == {responses.STATUS_NOT_AVAILABLE}
    assert inference_calls(companion) == 0
    assert len(entry.runtime_data.bridge.store._entries) <= 1  # bounded per session


async def test_router_error_in_active_is_neutral_and_not_forwarded(hass, companion, monkeypatch):
    entry, entity = await load(hass, "active")
    import custom_components.kinetic_voice_router.voice_router.adapter as adapter

    monkeypatch.setattr(adapter, "route", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    result = await ask(entity, KNOWLEDGE)
    assert result.response.error_code is IntentResponseErrorCode.FAILED_TO_HANDLE
    assert inference_calls(companion) == 0
    assert entry.runtime_data.bridge.stats.snapshot()["router_errors"] == 1


async def test_unsupported_language_is_answered_by_the_router(hass, companion):
    _, entity = await load(hass, "active")
    result = await ask(entity, KNOWLEDGE, language="fr")
    assert result.response.speech == responses.UNSUPPORTED_LANGUAGE
    assert inference_calls(companion) == 0


# --- Spoken follow-ups in a short, existing HA conversation ----------------------------------


async def test_active_short_answer_reaches_hermes_in_same_chat_session(hass, companion):
    _, entity = await load(hass, "active")
    companion.answers = ["Trinkst du lieber Kaffee oder Tee?", "Tee ist eine gute Wahl."]
    log = ChatLog(conversation_id="coffee-chat")
    first = await ask(entity, "Frag mich ob ich Kaffee oder Tee mag.", cid="coffee-chat", log=log)
    assert first.response.speech == "Trinkst du lieber Kaffee oder Tee?"
    second = await ask(entity, "Tee", cid="coffee-chat", log=log)
    assert second.response.speech == "Tee ist eine gute Wahl."
    assert inference_calls(companion) == 2
    body = companion.inference_bodies[1]
    assert body["conversation_id"] == "coffee-chat"
    assert body["messages"][-2] == {"role": "assistant", "content": first.response.speech}
    assert body["messages"][-1] == {"role": "user", "content": "Tee"}


async def test_active_stt_one_letter_requests_repeat_then_accepts_answer(hass, companion):
    _, entity = await load(hass, "active")
    companion.answers = ["Trinkst du lieber Kaffee oder Tee?", "Alles klar, Tee."]
    log = ChatLog(conversation_id="stt-chat")
    await ask(entity, "Frag mich etwas.", cid="stt-chat", log=log)
    failed = await ask(entity, "T.", cid="stt-chat", log=log)
    assert failed.response.speech == responses.CHAT_FOLLOWUP_UNCLEAR
    assert inference_calls(companion) == 1
    understood = await ask(entity, "Tee", cid="stt-chat", log=log)
    assert understood.response.speech == "Alles klar, Tee."
    assert inference_calls(companion) == 2


async def test_active_followup_cannot_execute_or_forward_device_actions(hass, companion):
    _, entity = await load(hass, "active")
    companion.answers = ["Trinkst du lieber Kaffee oder Tee?"]
    log = ChatLog(conversation_id="safe-chat")
    await ask(entity, "Frag mich etwas.", cid="safe-chat", log=log)
    blocked = await ask(entity, "Schalte das Licht an", cid="safe-chat", log=log)
    assert blocked.response.speech == responses.NOT_EXECUTED
    assert inference_calls(companion) == 1


async def test_active_device_question_does_not_arm_chat_followup(hass, companion):
    entry, entity = await load(hass, "active")
    companion.answers = ["Welche Lampe meinst du?"]
    log = ChatLog(conversation_id="device-chat")
    await ask(entity, KNOWLEDGE, cid="device-chat", log=log)
    assert not entry.runtime_data.bridge.store.pop_chat_followup("device-chat")
    result = await ask(entity, "Ja", cid="device-chat", log=log)
    assert result.response.speech == responses.NOT_UNDERSTOOD
    assert inference_calls(companion) == 1


async def test_active_no_question_no_cross_session_and_missing_history(hass, companion):
    entry, entity = await load(hass, "active")
    companion.answers = ["Eine Antwort ohne Frage."]
    log = ChatLog(conversation_id="c1")
    await ask(entity, KNOWLEDGE, cid="c1", log=log)
    assert not entry.runtime_data.bridge.store.pop_chat_followup("c1")
    result = await ask(entity, "Tee", cid="c1", log=log)
    assert result.response.speech == responses.CLARIFICATION_TEXT[ClarificationKind.QUESTION_OR_DEVICE]
    assert inference_calls(companion) == 1


# --- Hermes failures in every mode -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["off", "observe", "active"])
async def test_hermes_error_is_a_clean_error_response(hass, companion, mode):
    entry, entity = await load(hass, mode)
    companion.inference_status = 502
    result = await ask(entity, KNOWLEDGE, cid="x")
    assert result.response.error_code is IntentResponseErrorCode.FAILED_TO_HANDLE
    if mode == "active":
        assert (
            result.response.speech == responses.LIVE_FAILURE_TEXT[FailureCode.PROVIDER_UNAVAILABLE]
        )
    else:
        assert result.response.speech == FAILED
    assert "secret detail" not in repr(result.response.speech)
    assert entry.runtime_data.connection.code == "unknown"  # a real observation, not "ok"


async def test_status_recovers_after_a_successful_answer(hass, companion):
    entry, entity = await load(hass, "off")
    companion.inference_status = 500
    await ask(entity, KNOWLEDGE)
    assert entry.runtime_data.connection.code != "ok"
    companion.inference_status = 200
    await ask(entity, KNOWLEDGE)
    assert entry.runtime_data.connection.code == "ok"


async def test_token_rejected_during_a_turn_is_reported_as_auth_failure(hass, companion):
    entry, entity = await load(hass, "off")
    companion.token = "rotated-on-the-companion"  # noqa: S105
    result = await ask(entity, KNOWLEDGE)
    assert result.response.error_code is IntentResponseErrorCode.FAILED_TO_HANDLE
    assert entry.runtime_data.connection.code == "auth_failed"
    assert TOKEN not in repr(result)


async def test_timeout_is_an_error_response_not_a_hang(hass, companion):
    _, entity = await load(hass, "off")
    from custom_components.kinetic_voice_router.hermes_client import HermesClient

    entity._runtime.client = HermesClient(
        hass.session, companion.base_url, TOKEN, inference_timeout=0.2
    )
    companion.delay = 1.0
    result = await ask(entity, KNOWLEDGE)
    assert result.response.error_code is IntentResponseErrorCode.FAILED_TO_HANDLE


# --- Request content and privacy -----------------------------------------------------------------


async def test_history_is_bounded_and_uses_the_ha_session_id(hass, companion):
    from conftest import AssistantContent, UserContent

    _, entity = await load(hass, "off")
    history = []
    for i in range(30):
        history.append(UserContent(f"frage {i}"))
        history.append(AssistantContent("a", f"antwort {i}"))
    log = ChatLog(history, conversation_id="ha-session")
    await ask(entity, "und jetzt?", cid=None, log=log)
    body = companion.inference_bodies[0]
    assert len(body["messages"]) <= 20
    assert body["conversation_id"] == "ha-session"  # None from HA input falls back to the session
    assert body["language"] == "de"


async def test_nothing_sensitive_is_logged_in_any_mode(hass, companion, caplog):
    caplog.set_level(logging.DEBUG)
    for mode in ("off", "observe", "active"):
        hass.config_entries._entries.clear()
        hass.entities.clear()
        _, entity = await load(hass, mode)
        companion.answers = ["Das ist die geheime Antwort."]
        await ask(entity, "Das ist der geheime Satz über die Alpen", cid="cid-4711")
        await ask(entity, WARP, cid="cid-4711")
    for secret in (TOKEN, "geheime", "cid-4711", "Alpen", "Warp"):
        assert secret not in caplog.text


async def test_the_agent_never_acts_on_home_assistant(hass, companion):
    """No service call, no state write, no exposure change: the stub hass has no such API."""
    _, entity = await load(hass, "active")
    for text in (WARP, EXPLAIN, "Schalte das Licht an", "Ja", KNOWLEDGE):
        await ask(entity, text)
    assert set(vars(hass)) == {
        "data",
        "config",
        "config_entries",
        "reload_calls",
        "reload_requests",
        "entities",
        "session",
        "companion",
        "session_verify_ssl",
    }
