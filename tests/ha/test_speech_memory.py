"""Adaptive Speech Memory end to end: conversation, persistence, options UI, privacy.

Real conversation entity, router and HermesClient against the local fake companion;
Home Assistant parts are contract stubs (see conftest.py). Synthetic data only.
"""

from __future__ import annotations

import logging

from conftest import TOKEN, ChatLog, ConfigEntry, ConversationInput, FakeHass, Store

from custom_components.kinetic_voice_router import diagnostics
from custom_components.kinetic_voice_router.config_flow import KineticVoiceRouterConfigFlow
from custom_components.kinetic_voice_router.const import (
    CONF_CATEGORY,
    CONF_ENTRY,
    CONF_HEARD,
    CONF_INTENDED,
    CONF_MODE,
    CONF_SPEECH_MEMORY,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
)
from custom_components.kinetic_voice_router.speech_store import STORE_KEY
from custom_components.kinetic_voice_router.voice_router import responses

ASK = "Erzähl mir etwas über Mulahn"
CORRECT = "Nein, ich meinte Mulan."
PROPOSAL = "Soll ich mir merken, dass mit „Mulahn“ „Mulan“ gemeint ist?"


async def load(hass: FakeHass, mode: str = "active", *, learning: bool = True):
    options = {CONF_MODE: mode}
    if learning is not None:
        options[CONF_SPEECH_MEMORY] = learning
    entry = hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            data={CONF_URL: hass.companion.base_url, CONF_TOKEN: TOKEN, CONF_VERIFY_TLS: True},
            options=options,
            minor_version=3,
        )
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    return entry, hass.entities[entry.entry_id][0]


async def restart(hass: FakeHass, entry):
    """Unload + set up again: runtime objects are rebuilt, only the Store file stays."""
    await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return hass.entities[entry.entry_id][0]


async def say(entity, text: str, log: ChatLog, cid: str | None = None):
    return await entity.async_process(ConversationInput(text, cid, "de"), log)


def stored_pairs(hass: FakeHass) -> list[tuple[str, str]]:
    raw = hass.storage_files.get(STORE_KEY)
    if raw is None:
        return []
    return [(e["heard"], e["intended"]) for e in raw["data"]["entries"]]


def last_user_message(companion) -> str:
    return [m for m in companion.inference_bodies[-1]["messages"] if m["role"] == "user"][-1][
        "content"
    ]


def options_flow(hass, entry):
    flow = KineticVoiceRouterConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    flow.config_entry = entry
    return flow


# --- Learning in a conversation ------------------------------------------------------------


async def test_confirmed_correction_continues_request_learns_and_survives_restart(hass, companion):
    entry, entity = await load(hass)
    companion.answers = [
        "Mulahn kenne ich nicht.",
        "Mulan ist ein Disney-Film über eine junge Kriegerin.",
        "Mulan basiert auf einer chinesischen Ballade.",
    ]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)

    corrected = await say(entity, CORRECT, log)
    # the ORIGINAL request is answered with the corrected word, no repetition needed
    assert last_user_message(companion) == "Erzähl mir etwas über Mulan"
    assert corrected.response.speech == (
        "Mulan ist ein Disney-Film über eine junge Kriegerin. " + PROPOSAL
    )
    assert stored_pairs(hass) == []  # nothing stored before the explicit yes

    calls = len(companion.inference_bodies)
    learned = await say(entity, "Ja", log)
    assert learned.response.speech == "Gemerkt: Mit „Mulahn“ meinst du „Mulan“."
    assert len(companion.inference_bodies) == calls  # "Ja" is not forwarded
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]

    entity = await restart(hass, entry)
    later = await say(entity, ASK, ChatLog(conversation_id="s2"))
    assert last_user_message(companion) == "Erzähl mir etwas über Mulan"  # no new question
    assert later.response.speech == "Mulan basiert auf einer chinesischen Ballade."


async def test_decline_stores_nothing(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    result = await say(entity, "Nein", log)
    assert result.response.speech == responses.ASM_NOT_LEARNED
    assert stored_pairs(hass) == []


async def test_unrelated_answer_drops_the_proposal(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film.", "Es ist Mittag."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    other = await say(entity, "Wie spät ist es?", log)
    assert other.response.speech == "Es ist Mittag."
    late_yes = await say(entity, "Ja", log)
    assert late_yes.response.speech != "Gemerkt: Mit „Mulahn“ meinst du „Mulan“."
    assert stored_pairs(hass) == []


async def test_expired_proposal_stores_nothing(hass, companion):
    entry, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    clock = [5000.0]
    entry.runtime_data.bridge.store._clock = lambda: clock[0]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    clock[0] += 61
    result = await say(entity, "Ja", log)
    assert result.response.speech == responses.NOT_UNDERSTOOD  # a bare "Ja", no approval
    assert stored_pairs(hass) == []


async def test_yes_in_another_session_stores_nothing(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="a")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    await say(entity, "Ja", ChatLog(conversation_id="b"))
    assert stored_pairs(hass) == []


async def test_unreliable_misheard_word_is_never_guessed(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Gern."]
    log = ChatLog(conversation_id="s1")
    await say(entity, "Erzähl mir etwas über Mulahn und Mulahm", log)
    result = await say(entity, CORRECT, log)
    assert PROPOSAL not in result.response.speech
    assert "merken" not in result.response.speech
    # Hermes still gets the user's own words and the history; nothing is rewritten
    assert last_user_message(companion) == CORRECT


async def test_learning_off_changes_nothing(hass, companion):
    _, entity = await load(hass, learning=False)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    result = await say(entity, CORRECT, log)
    assert result.response.speech == "Mulan ist ein Film."
    assert last_user_message(companion) == CORRECT
    assert hass.storage_writes == 0


async def test_learned_pairs_unused_while_learning_off(hass, companion):
    hass.storage_files[STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "entries": [
                {
                    "heard": "Mulahn",
                    "intended": "Mulan",
                    "category": "stt",
                    "source": "manual",
                    "confirmed_on": "2026-10-31",
                }
            ]
        },
    }
    _, entity = await load(hass, learning=False)
    await say(entity, ASK, ChatLog(conversation_id="s1"))
    assert last_user_message(companion) == ASK


async def test_off_and_observe_never_use_speech_memory(hass, companion):
    for mode in ("off", "observe"):
        hass.config_entries._entries.clear()
        hass.entities.clear()
        _, entity = await load(hass, mode)
        companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
        log = ChatLog(conversation_id=f"s-{mode}")
        await say(entity, ASK, log)
        result = await say(entity, CORRECT, log)
        assert "merken" not in result.response.speech
        assert last_user_message(companion) == CORRECT
    assert stored_pairs(hass) == []


async def test_conflicting_pair_asks_before_replacing(hass, companion):
    entry, entity = await load(hass)
    await entry.runtime_data.speech.async_add(
        "Mulahn",
        "Moulin",
        category=__import__(
            "custom_components.kinetic_voice_router.voice_router.speech_memory",
            fromlist=["Category"],
        ).Category.NAME,
        source=__import__(
            "custom_components.kinetic_voice_router.voice_router.speech_memory",
            fromlist=["Source"],
        ).Source.MANUAL,
    )
    companion.answers = ["Moulin ist ein Ort.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, "Erzähl mir etwas über Mulahm", log)  # no rule for this spelling
    await say(entity, ASK, ChatLog(conversation_id="other"))  # rule Mulahn->Moulin applies
    assert last_user_message(companion) == "Erzähl mir etwas über Moulin"
    log = ChatLog(conversation_id="s2")
    log.content.append(__import__("conftest").UserContent(ASK))
    log.content.append(
        __import__("conftest").AssistantContent(
            "conversation.kinetic_voice_router", "Moulin ist ein Ort."
        )
    )
    companion.answers = ["Mulan ist ein Film."]
    result = await say(entity, CORRECT, log)
    assert result.response.speech.endswith(
        "Bisher verstehe ich „Mulahn“ als „Moulin“. Soll ich mir stattdessen „Mulan“ merken?"
    )
    assert stored_pairs(hass) == [("Mulahn", "Moulin")]  # untouched until "yes"
    await say(entity, "Ja", log)
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]


async def test_common_word_is_stored_as_ambiguous_and_not_applied(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Bill Gates gründete Microsoft.", "Unbekannt."]
    log = ChatLog(conversation_id="s1")
    await say(entity, "Wer war Bild Gates", log)
    await say(entity, "ich meinte Bill", log)
    learned = await say(entity, "Ja", log)
    assert learned.response.speech.startswith("Gemerkt. Weil „Bild“ ein gängiges Wort ist")
    assert hass.storage_files[STORE_KEY]["data"]["entries"][0]["category"] == "ambiguous"
    await say(entity, "Wer war Bild Gates", ChatLog(conversation_id="s2"))
    assert last_user_message(companion) == "Wer war Bild Gates"  # never replaced automatically


async def test_one_letter_reply_asks_again_and_learns_nothing(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Möchtest du Kaffee oder Tee?", "Gute Wahl, Tee."]
    log = ChatLog(conversation_id="s1")
    await say(entity, "Frag mich etwas.", log)
    unclear = await say(entity, "T.", log)
    assert unclear.response.speech == (
        "Ich habe dich nicht richtig verstanden. Möchtest du Kaffee oder Tee?"
    )
    understood = await say(entity, "Tee", log)
    assert understood.response.speech == "Gute Wahl, Tee."
    assert stored_pairs(hass) == []


# --- Safety -------------------------------------------------------------------------------


async def test_learned_words_never_touch_device_commands_or_status(hass, companion):
    entry, entity = await load(hass)
    speech = entry.runtime_data.speech
    from custom_components.kinetic_voice_router.voice_router.speech_memory import (
        Category,
        Source,
    )

    await speech.async_add("Mulahn", "Mulan", category=Category.STT, source=Source.MANUAL)
    for text, expected in (
        ("Schalte Mulahn an", responses.NOT_EXECUTED),
        ("Mulahn aus", responses.NOT_EXECUTED),
        ("Mach Mulahn heller", responses.NOT_EXECUTED),
    ):
        result = await say(entity, text, ChatLog(conversation_id=text))
        assert result.response.speech == expected
    assert companion.inference_bodies == []
    # a status-like sentence the router forwards stays exactly as heard
    await say(entity, "Ist Mulahn an?", ChatLog(conversation_id="status"))
    assert last_user_message(companion) == "Ist Mulahn an?"


async def test_device_words_cannot_be_learned_in_conversation(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Was meinst du?", "Gern."]
    log = ChatLog(conversation_id="s1")
    await say(entity, "Erzähl mir etwas über Lich", log)
    result = await say(entity, "Nein, ich meinte Licht", log)
    assert "merken" not in result.response.speech
    await say(entity, "Ja", log)
    assert stored_pairs(hass) == []


async def test_invented_device_action_in_continued_answer_is_still_filtered(hass, companion):
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Ich habe das Licht eingeschaltet."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    result = await say(entity, CORRECT, log)
    assert result.response.speech.startswith(responses.NOT_EXECUTED)
    assert "eingeschaltet" not in result.response.speech


async def test_nothing_sensitive_is_logged_or_stored(hass, companion, caplog):
    caplog.set_level(logging.DEBUG)
    _, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="cid-secret-77")
    await say(entity, ASK, log, cid="cid-secret-77")
    await say(entity, CORRECT, log, cid="cid-secret-77")
    await say(entity, "Ja", log, cid="cid-secret-77")
    dumped = repr(hass.storage_files)
    for secret in ("cid-secret-77", "Erzähl", "Film", TOKEN):
        assert secret not in dumped
        assert secret not in caplog.text
    assert hass.storage_files[STORE_KEY]["key"] == STORE_KEY


# --- Persistence robustness ------------------------------------------------------------------


async def test_invalid_stored_data_is_left_untouched_and_locked(hass, companion):
    broken = {"version": 1, "minor_version": 1, "key": STORE_KEY, "data": {"entries": "x"}}
    hass.storage_files[STORE_KEY] = dict(broken)
    entry, entity = await load(hass)
    speech = entry.runtime_data.speech
    assert speech.status == "invalid" and not speech.writable
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    result = await say(entity, CORRECT, log)
    assert "merken" not in result.response.speech  # no learning into a locked store
    assert hass.storage_files[STORE_KEY] == broken  # never overwritten silently
    assert hass.storage_writes == 0


async def test_newer_store_version_is_left_untouched(hass, companion):
    newer = {"version": 9, "minor_version": 1, "key": STORE_KEY, "data": {"entries": []}}
    hass.storage_files[STORE_KEY] = dict(newer)
    entry, _ = await load(hass)
    assert entry.runtime_data.speech.status == "unreadable"
    assert hass.storage_files[STORE_KEY] == newer


async def test_corrupt_json_is_handled_by_home_assistant(hass, companion):
    hass.storage_files[STORE_KEY] = Store.CORRUPT
    entry, _ = await load(hass)
    # HA moves the broken file aside and raises a repair issue; the copy is kept
    assert f"{STORE_KEY}.corrupt" in hass.storage_files
    assert hass.repair_issues == [f"storage_corruption_{STORE_KEY}"]
    assert entry.runtime_data.speech.status == "ok" and len(entry.runtime_data.speech.memory) == 0


async def test_store_is_private_atomic_and_versioned(hass, companion):
    entry, _ = await load(hass)
    store = entry.runtime_data.speech._store
    assert (store.private, store.atomic_writes, store.version) == (True, True, 1)


async def test_removing_the_integration_removes_the_lexicon(hass, companion):
    from custom_components.kinetic_voice_router import async_remove_entry

    entry, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    await say(entity, "Ja", log)
    assert stored_pairs(hass)
    await async_remove_entry(hass, entry)
    assert STORE_KEY not in hass.storage_files


# --- Options UI -----------------------------------------------------------------------------


async def test_learning_is_off_by_default_and_switchable(hass, companion):
    entry, _ = await load(hass, learning=None)
    assert entry.runtime_data.speech_enabled is False
    flow = options_flow(hass, entry)
    page = await flow.async_step_speech_memory()
    assert page["type"] == "menu"
    assert "**Lernen:** aus (Standard)" in page["description_placeholders"]["overview"]
    form = await flow.async_step_speech_memory_toggle()
    marker = next(iter(form["data_schema"].schema))
    assert marker.default() is False
    saved = await flow.async_step_speech_memory_toggle({CONF_SPEECH_MEMORY: True})
    assert saved["data"] == {CONF_MODE: "active", CONF_SPEECH_MEMORY: True}
    await hass.config_entries.async_update_options(entry, saved["data"])
    assert entry.runtime_data.speech_enabled is True


async def test_saving_the_mode_keeps_the_learning_switch(hass, companion):
    entry, _ = await load(hass)
    saved = await options_flow(hass, entry).async_step_settings({CONF_MODE: "observe"})
    assert saved["data"] == {CONF_MODE: "observe", CONF_SPEECH_MEMORY: True}


async def test_add_edit_delete_and_overview(hass, companion):
    entry, _ = await load(hass)
    flow = options_flow(hass, entry)
    page = await flow.async_step_speech_memory_add(
        {CONF_HEARD: "Mulahn", CONF_INTENDED: "Mulan", CONF_CATEGORY: "name"}
    )
    assert page["step_id"] == "speech_memory"
    overview = page["description_placeholders"]["overview"]
    assert "**Mulahn** → **Mulan** · Eigenname · manuell eingetragen am" in overview
    assert page["menu_options"] == [
        "speech_memory_toggle",
        "speech_memory_add",
        "speech_memory_edit",
        "speech_memory_delete",
        "speech_memory_reset_confirm",
        "init",
    ]
    form = await flow.async_step_speech_memory_edit({CONF_ENTRY: "mulahn"})
    assert form["step_id"] == "speech_memory_edit_entry"
    assert form["description_placeholders"] == {"heard": "Mulahn"}
    page = await flow.async_step_speech_memory_edit_entry(
        {CONF_INTENDED: "Mulan Film", CONF_CATEGORY: "term"}
    )
    assert stored_pairs(hass) == [("Mulahn", "Mulan Film")]
    assert "Fachbegriff" in page["description_placeholders"]["overview"]
    page = await flow.async_step_speech_memory_delete({CONF_ENTRY: "mulahn"})
    assert stored_pairs(hass) == []
    assert "Noch keine bestätigten Begriffe." in page["description_placeholders"]["overview"]


async def test_add_rejections_are_explained(hass, companion):
    entry, _ = await load(hass)
    flow = options_flow(hass, entry)
    for heard, intended, error in (
        ("T", "Tee", "asm_too_short"),
        ("Licht", "Lich", "asm_protected"),
        ("Wohnzimmer", "Wohnzimer", "asm_protected"),
        ("Mul4hn", "Mulan", "asm_invalid"),
        ("Mulan", "Mulan", "asm_same"),
    ):
        form = await flow.async_step_speech_memory_add(
            {CONF_HEARD: heard, CONF_INTENDED: intended, CONF_CATEGORY: "name"}
        )
        assert form["errors"] == {"base": error}, heard
    await flow.async_step_speech_memory_add(
        {CONF_HEARD: "Mulahn", CONF_INTENDED: "Mulan", CONF_CATEGORY: "name"}
    )
    form = await flow.async_step_speech_memory_add(
        {CONF_HEARD: "Mulahn", CONF_INTENDED: "Moulin", CONF_CATEGORY: "name"}
    )
    assert form["errors"] == {"base": "asm_conflict"}


async def test_reset_needs_confirmation_and_cancel_keeps_entries(hass, companion):
    entry, _ = await load(hass)
    flow = options_flow(hass, entry)
    await flow.async_step_speech_memory_add(
        {CONF_HEARD: "Mulahn", CONF_INTENDED: "Mulan", CONF_CATEGORY: "name"}
    )
    await flow.async_step_speech_memory_reset_execute()  # without confirmation
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]
    confirm = await flow.async_step_speech_memory_reset_confirm()
    assert confirm["menu_options"] == ["speech_memory_reset_execute", "speech_memory"]
    await flow.async_step_speech_memory()  # "Abbrechen"
    await flow.async_step_speech_memory_reset_execute()
    assert stored_pairs(hass) == [("Mulahn", "Mulan")]
    await flow.async_step_speech_memory_reset_confirm()
    await flow.async_step_speech_memory_reset_execute()
    assert stored_pairs(hass) == []


async def test_locked_store_shows_warning_and_reset_repairs_it(hass, companion):
    hass.storage_files[STORE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"entries": "x"},
    }
    entry, _ = await load(hass)
    flow = options_flow(hass, entry)
    page = await flow.async_step_speech_memory()
    assert "ungültig und wurde nicht verändert" in page["description_placeholders"]["overview"]
    form = await flow.async_step_speech_memory_add(
        {CONF_HEARD: "Mulahn", CONF_INTENDED: "Mulan", CONF_CATEGORY: "name"}
    )
    assert form["errors"] == {"base": "asm_read_only"}
    await flow.async_step_speech_memory_reset_confirm()
    await flow.async_step_speech_memory_reset_execute()
    assert entry.runtime_data.speech.writable
    assert hass.storage_files[STORE_KEY]["data"] == {"entries": []}


async def test_unloaded_entry_shows_unavailable(hass, companion):
    entry = hass.config_entries.add(
        ConfigEntry(domain=DOMAIN, entry_id="x", options={CONF_MODE: "off"}, minor_version=3)
    )
    page = await options_flow(hass, entry).async_step_speech_memory()
    assert page["step_id"] == "speech_memory_unavailable"


async def test_diagnostics_contain_counts_not_words(hass, companion):
    entry, entity = await load(hass)
    companion.answers = ["Unbekannt.", "Mulan ist ein Film."]
    log = ChatLog(conversation_id="s1")
    await say(entity, ASK, log)
    await say(entity, CORRECT, log)
    await say(entity, "Ja", log)
    diag = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert diag["speech_memory"] == {
        "learning_enabled": True,
        "storage_status": "ok",
        "entries": 1,
    }
    assert "Mulahn" not in repr(diag) and "Mulan" not in repr(diag)
