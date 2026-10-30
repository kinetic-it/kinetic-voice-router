"""Options flow: menu, mode, test request (simulation), runtime statistics, connection page.

Ported from the 0.4.x suite and adapted to the standalone integration: the router now
lives in the entry's runtime data, there is no `hass.data` bridge any more.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from conftest import TOKEN, ConfigEntry, FakeCompanion, FakeHass

from custom_components.kinetic_voice_router import runtime_stats
from custom_components.kinetic_voice_router.config_flow import (
    KineticVoiceRouterConfigFlow,
    KineticVoiceRouterOptionsFlow,
)
from custom_components.kinetic_voice_router.const import (
    CONF_MODE,
    CONF_TEST_SENTENCE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
    INTEGRATION_VERSION,
    STATS_KEY,
)
from custom_components.kinetic_voice_router.voice_router import RuntimeStats

ROOT = Path(__file__).resolve().parents[2]


def options_flow(hass: FakeHass, entry: ConfigEntry) -> KineticVoiceRouterOptionsFlow:
    flow = KineticVoiceRouterConfigFlow.async_get_options_flow(entry)
    flow.hass = hass
    flow.config_entry = entry
    return flow


async def set_up(hass: FakeHass, options: dict | None = None) -> ConfigEntry:
    entry = hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            title="Kinetic Voice Router",
            data={
                CONF_URL: hass.companion.base_url,
                CONF_TOKEN: TOKEN,
                CONF_VERIFY_TLS: True,
            },
            options={CONF_MODE: "off"} if options is None else options,
            minor_version=3,
        )
    )
    await hass.config_entries.async_setup(entry.entry_id)
    return entry


def bridge_of(hass: FakeHass):
    return hass.config_entries.async_entries(DOMAIN)[0].runtime_data.bridge


async def save_mode(hass: FakeHass, entry: ConfigEntry, user_input: dict) -> dict:
    result = await options_flow(hass, entry).async_step_settings(user_input)
    if result["type"] == "create_entry":
        await hass.config_entries.async_update_options(entry, result["data"])
    return result


def schema_default(result: dict, key: str) -> object:
    for marker in result["data_schema"].schema:
        if str(marker) == key:
            return marker.default()
    raise AssertionError(f"{key} missing from schema")


# --- Optionen: Menü und Betriebsart -------------------------------------------------------


async def test_options_open_as_menu_with_real_info(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    menu = await options_flow(hass, entry).async_step_init()
    assert menu["type"] == "menu"
    assert menu["menu_options"] == ["settings", "connection", "test", "statistics"]
    assert menu["description_placeholders"] == {
        "version": INTEGRATION_VERSION,
        "router_version": INTEGRATION_VERSION,
        "mode": "Beobachten",
        "hermes_status": "Hermes Companion erreichbar und kompatibel",
    }


async def test_menu_status_is_a_real_observation_not_a_guess(hass: FakeHass) -> None:
    entry = await set_up(hass)
    # no setup happened for a fresh, never loaded entry object
    stale = ConfigEntry(domain=DOMAIN, entry_id="x", data=dict(entry.data), minor_version=3)
    menu = await options_flow(hass, stale).async_step_init()
    assert (
        menu["description_placeholders"]["hermes_status"] == "Hermes Companion nicht eingerichtet"
    )


# --- Hermes-Verbindung ------------------------------------------------------------------


async def test_connection_page_runs_a_real_probe_and_hides_url_and_token(
    hass: FakeHass, companion: FakeCompanion
) -> None:
    entry = await set_up(hass)
    before = len(companion.requests)
    page = await options_flow(hass, entry).async_step_connection()
    assert page["type"] == "menu"
    assert page["menu_options"] == ["connection", "init"]
    assert len(companion.requests) - before == 2  # /health + /v1/capabilities
    placeholders = page["description_placeholders"]
    assert placeholders == {
        "status": "Hermes Companion erreichbar und kompatibel",
        "api_version": "1.0",
        "companion_version": "9.9.9",
        "tls": "an",
    }
    dumped = repr(page)
    assert TOKEN not in dumped and companion.base_url not in dumped


async def test_connection_page_reports_failures_honestly(
    hass: FakeHass, companion: FakeCompanion
) -> None:
    entry = await set_up(hass)
    flow = options_flow(hass, entry)
    companion.token = "rotated-on-the-companion"  # noqa: S105
    page = await flow.async_step_connection()
    assert page["description_placeholders"]["status"] == "Hermes Companion lehnt den Token ab"
    assert entry.runtime_data.connection.code == "auth_failed"
    companion.token = TOKEN
    companion.api_version = "2.0"
    page = await flow.async_step_connection()
    assert (
        page["description_placeholders"]["status"] == "Hermes Companion: inkompatible API-Version"
    )
    companion.api_version = "1.0"
    page = await flow.async_step_connection()  # "Erneut prüfen"
    assert (
        page["description_placeholders"]["status"] == "Hermes Companion erreichbar und kompatibel"
    )
    assert entry.runtime_data.connection.code == "ok"


async def test_connection_page_without_credentials_is_not_configured(hass: FakeHass) -> None:
    entry = hass.config_entries.add(
        ConfigEntry(domain=DOMAIN, entry_id="legacy", options={CONF_MODE: "off"}, minor_version=3)
    )
    page = await options_flow(hass, entry).async_step_connection()
    assert page["description_placeholders"]["status"] == "Hermes Companion nicht eingerichtet"


async def test_connection_page_shows_tls_setting(hass: FakeHass) -> None:
    entry = await set_up(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_VERIFY_TLS: False})
    page = await options_flow(hass, entry).async_step_connection()
    assert page["description_placeholders"]["tls"] == "aus"


async def test_settings_default_is_stored_mode(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "active"})
    form = await options_flow(hass, entry).async_step_settings()
    assert form["step_id"] == "settings"
    assert form["description_placeholders"] == {"mode": "Aktiv"}
    assert schema_default(form, CONF_MODE) == "active"
    assert [str(key) for key in form["data_schema"].schema] == [CONF_MODE]


@pytest.mark.parametrize("mode", ["off", "observe", "active"])
async def test_settings_save_each_mode(hass: FakeHass, mode: str) -> None:
    entry = await set_up(hass)
    result = await save_mode(hass, entry, {CONF_MODE: mode})
    assert result["data"] == {CONF_MODE: mode}
    assert entry.options == {CONF_MODE: mode}
    assert hass.reload_calls == [entry.entry_id]


async def test_settings_without_field_keeps_stored_mode(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    result = await save_mode(hass, entry, {})
    assert result["data"] == {CONF_MODE: "observe"}


@pytest.mark.parametrize("submitted", ["Aktiv", "on", True, 1, None])
async def test_settings_invalid_mode_shows_error_and_keeps_value(
    hass: FakeHass, submitted: object
) -> None:
    entry = await set_up(hass, {CONF_MODE: "active"})
    result = await save_mode(hass, entry, {CONF_MODE: submitted})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_mode"}
    assert schema_default(result, CONF_MODE) == "active"
    assert entry.options == {CONF_MODE: "active"}
    assert hass.reload_calls == []


async def test_saving_mode_drops_legacy_key(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "off", "router_enabled": True})
    await save_mode(hass, entry, {CONF_MODE: "off"})
    assert entry.options == {CONF_MODE: "off"}


# --- Testanfrage (Simulation) -------------------------------------------------------------


STATUS_RESULT_DE = {
    "route": "Geräte- oder Statusanfrage (ohne Ausführung) (`CONTROL_FALLBACK`)",
    "rule": "R-STATUS-01",
    "reason": "Statusanfrage zu einem Gerät – der Router kennt keinen Gerätezustand.",
    "answer": "Den Gerätezustand kann ich von hier aus nicht abfragen.",
}


def schema_default_missing(result: dict, key: str) -> bool:
    import voluptuous as vol

    for marker in result["data_schema"].schema:
        if str(marker) == key:
            return marker.default is vol.UNDEFINED
    raise AssertionError(f"{key} missing from schema")


async def test_test_step_first_open_is_empty_form(hass: FakeHass) -> None:
    entry = await set_up(hass)
    form = await options_flow(hass, entry).async_step_test()
    assert form["type"] == "form"
    assert form["step_id"] == "test"
    assert [str(key) for key in form["data_schema"].schema] == [CONF_TEST_SENTENCE]
    assert schema_default_missing(form, CONF_TEST_SENTENCE)
    assert not form.get("description_placeholders")
    assert form["errors"] == {}


@pytest.mark.parametrize("mode", ["off", "observe", "active"])
async def test_test_result_page_in_every_mode_without_side_effects(
    hass: FakeHass, mode: str
) -> None:
    entry = await set_up(hass, {CONF_MODE: mode})
    bridge = bridge_of(hass)
    before_options = dict(entry.options)
    before_stats = runtime_stats(hass).snapshot()["decisions"]
    flow = options_flow(hass, entry)
    result = await flow.async_step_test({CONF_TEST_SENTENCE: "Ist die Staubsaugersteckdose an?"})
    assert result["type"] == "menu"
    assert result["step_id"] == "test_result"
    assert result["menu_options"] == ["test", "init"]
    assert result["description_placeholders"] == STATUS_RESULT_DE
    assert dict(entry.options) == before_options
    assert hass.reload_calls == []
    assert runtime_stats(hass).snapshot()["decisions"] == before_stats
    assert bridge.store._entries == {}
    assert bridge.mode.value == mode


async def test_test_result_stores_no_sentence(hass: FakeHass) -> None:
    entry = await set_up(hass)
    flow = options_flow(hass, entry)
    await flow.async_step_test({CONF_TEST_SENTENCE: "Ist die Wohnzimmerlampe von Oma an?"})
    dumped = repr(vars(flow)).lower()
    assert "oma" not in dumped
    assert "wohnzimmerlampe" not in dumped


async def test_new_request_from_result_page_is_empty_again(hass: FakeHass) -> None:
    entry = await set_up(hass)
    flow = options_flow(hass, entry)
    await flow.async_step_test({CONF_TEST_SENTENCE: "Ist die Staubsaugersteckdose an?"})
    again = await flow.async_step_test()  # menu entry "Neue Anfrage"
    assert again["type"] == "form"
    assert schema_default_missing(again, CONF_TEST_SENTENCE)
    second = await flow.async_step_test({CONF_TEST_SENTENCE: "Erzähl mir etwas über die Alpen"})
    assert second["description_placeholders"]["route"] == "Gespräch/Wissen (`CHAT`)"
    assert second["description_placeholders"]["answer"] == (
        "(würde an Hermes weitergegeben – im Test kein Aufruf)"
    )
    back = await flow.async_step_init()  # menu entry "Zurück zur Übersicht"
    assert back["type"] == "menu"
    assert back["step_id"] == "init"


async def test_result_page_without_result_shows_input(hass: FakeHass) -> None:
    entry = await set_up(hass)
    page = await options_flow(hass, entry).async_step_test_result()
    assert page["type"] == "form"
    assert page["step_id"] == "test"


async def test_test_step_confirmation_and_explain_have_no_state(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "active"})
    flow = options_flow(hass, entry)
    await flow.async_step_test({CONF_TEST_SENTENCE: "Licht"})
    yes = await flow.async_step_test({CONF_TEST_SENTENCE: "Ja"})
    assert yes["description_placeholders"]["rule"] == "R-CONFIRM-01"
    why = await flow.async_step_test({CONF_TEST_SENTENCE: "Warum hat das nicht funktioniert?"})
    assert why["description_placeholders"]["answer"] == (
        "Dazu liegt mir kein sicherer Fehlergrund vor."
    )


@pytest.mark.parametrize("value", [None, "", "   ", 5])
async def test_test_step_empty_input_error(hass: FakeHass, value: object) -> None:
    entry = await set_up(hass)
    result = await options_flow(hass, entry).async_step_test({CONF_TEST_SENTENCE: value})
    assert result["type"] == "form"
    assert result["step_id"] == "test"
    assert result["errors"] == {"base": "empty_test_sentence"}


async def test_test_step_logs_nothing(hass: FakeHass, caplog: pytest.LogCaptureFixture) -> None:
    entry = await set_up(hass)
    with caplog.at_level(logging.DEBUG):
        await options_flow(hass, entry).async_step_test(
            {CONF_TEST_SENTENCE: "Geheimer Testsatz Wohnzimmerlampe"}
        )
    assert "Geheimer" not in caplog.text
    assert "wohnzimmerlampe" not in caplog.text.lower()


async def test_test_result_english(session) -> None:
    hass = FakeHass(language="en")
    hass.session = session
    hass.companion = type("C", (), {"base_url": "http://127.0.0.1:9"})()
    entry = hass.config_entries.add(
        ConfigEntry(domain=DOMAIN, entry_id="e", options={CONF_MODE: "off"}, minor_version=3)
    )
    result = await options_flow(hass, entry).async_step_test(
        {CONF_TEST_SENTENCE: "Erzähl mir etwas über die Alpen"}
    )
    # HA language "en": the German router reports an unsupported language - honestly.
    assert result["description_placeholders"]["reason"] == "Language not supported."


# --- Laufzeitstatistik --------------------------------------------------------------------


async def test_statistics_off_and_empty_message(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "off"})
    page = await options_flow(hass, entry).async_step_statistics()
    assert page["type"] == "menu"
    assert page["menu_options"] == ["statistics_details", "reset_confirm", "init"]
    summary = page["description_placeholders"]["summary"]
    assert summary.startswith("Router ist aus – es werden keine Routerentscheidungen erfasst.")
    assert "Noch keine erfassten Anfragen." in summary
    assert "Testanfragen zählen nicht." in summary
    assert "CHAT" not in summary and "under_2s" not in summary


async def test_statistics_summary_observe_and_active(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    for text in ("Ist das Licht aus?", "Erzähl mir einen Witz", "Licht an"):
        bridge_of(hass).observe(text=text, language="de")
    page = await options_flow(hass, entry).async_step_statistics()
    summary = page["description_placeholders"]["summary"]
    assert "**Beobachten:** 3 erfasste Anfragen" in summary
    assert "- würden an Hermes gehen: 1" in summary
    assert "- Router hätte geantwortet: 2" in summary
    assert "Router ist aus" not in summary
    assert "Noch keine" not in summary

    await save_mode(hass, entry, {CONF_MODE: "active"})

    async def ok() -> str:
        return "Die Alpen sind ein Hochgebirge."

    async def boom() -> str:
        raise ValueError("x")

    bridge = bridge_of(hass)
    for call in (ok, boom):
        await bridge.async_handle(
            text="Erzähl mir etwas über die Alpen",
            language="de",
            conversation_id="c",
            call_hermes=call,
            hermes_errors=(ValueError,),
        )
    summary = (await options_flow(hass, entry).async_step_statistics())["description_placeholders"][
        "summary"
    ]
    assert "**Aktiv:** 2 erfasste Anfragen" in summary
    assert "- an Hermes weitergegeben: 2" in summary
    assert "- Hermes-Fehler: 1" in summary


async def test_statistics_summary_shows_router_errors_only_when_present(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "active"})
    flow = options_flow(hass, entry)
    summary = (await flow.async_step_statistics())["description_placeholders"]["summary"]
    assert "Interne Routerfehler" not in summary
    runtime_stats(hass).record_router_error()
    summary = (await flow.async_step_statistics())["description_placeholders"]["summary"]
    assert "Interne Routerfehler (neutral beantwortet, nicht an Hermes): 1" in summary


async def test_statistics_details_human_labels_with_codes(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    bridge_of(hass).observe(text="Ist das Licht aus?", language="de")
    page = await options_flow(hass, entry).async_step_statistics_details()
    assert page["type"] == "menu"
    assert page["menu_options"] == ["statistics", "init"]
    details = page["description_placeholders"]["details"]
    assert "- Geräte- oder Statusanfrage (ohne Ausführung) (`CONTROL_FALLBACK`): 1" in details
    assert "- Zeitüberschreitung (`PROVIDER_TIMEOUT`): 0" in details
    assert "- unter 2 s: 0" in details


async def test_reset_only_after_explicit_confirmation(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    bridge_of(hass).observe(text="Licht an", language="de")
    flow = options_flow(hass, entry)

    def count() -> int:
        return runtime_stats(hass).snapshot()["decisions"]["observe"]["CONTROL_FALLBACK"]

    await flow.async_step_init()
    await flow.async_step_statistics()
    await flow.async_step_statistics_details()
    confirm = await flow.async_step_reset_confirm()
    assert confirm["type"] == "menu"
    assert confirm["menu_options"] == ["reset_execute", "statistics"]
    assert count() == 1  # opening and navigating never reset
    cancel = await flow.async_step_statistics()  # "Abbrechen"
    assert cancel["step_id"] == "statistics"
    assert count() == 1
    # R3.2 (#3): nach Abbrechen ist die Freigabe verbraucht, direktes Ausfuehren wirkt nicht
    after_cancel = await flow.async_step_reset_execute()
    assert after_cancel["step_id"] == "statistics"
    assert count() == 1
    # bewusste Bestaetigung setzt genau einmal zurueck
    await flow.async_step_reset_confirm()
    done = await flow.async_step_reset_execute()
    assert count() == 0
    assert done["step_id"] == "statistics"
    bridge_of(hass).observe(text="Licht an", language="de")
    await flow.async_step_reset_execute()  # zweites Ausfuehren ohne neue Bestaetigung
    assert count() == 1
    assert entry.options == {CONF_MODE: "observe"}
    assert hass.reload_calls == []


async def test_reset_execute_without_confirmation_never_resets(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    bridge_of(hass).observe(text="Licht an", language="de")

    def count() -> int:
        return runtime_stats(hass).snapshot()["decisions"]["observe"]["CONTROL_FALLBACK"]

    # direkt im frischen Flow
    page = await options_flow(hass, entry).async_step_reset_execute()
    assert page["step_id"] == "statistics"
    assert count() == 1
    # Bestaetigung, dann ueber Details oder Uebersicht weg: Freigabe verfaellt
    for leave in ("async_step_statistics_details", "async_step_init"):
        flow = options_flow(hass, entry)
        await flow.async_step_reset_confirm()
        await getattr(flow, leave)()
        await flow.async_step_reset_execute()
        assert count() == 1
    # Bestaetigung in einem anderen Flow gibt diesen Flow nicht frei
    other = options_flow(hass, entry)
    await options_flow(hass, entry).async_step_reset_confirm()
    await other.async_step_reset_execute()
    assert count() == 1


def test_reset_execute_only_offered_on_confirmation_page() -> None:
    """HA (data_entry_flow, vol.In(menu_options)) nimmt nur angebotene Menuepunkte an.
    reset_execute steht ausschliesslich im Menue der Bestaetigungsseite."""
    source = (ROOT / "custom_components" / DOMAIN / "config_flow.py").read_text(encoding="utf-8")
    menus = re.findall(r"menu_options=\[([^\]]*)\]", source)
    offering = [m for m in menus if "reset_execute" in m]
    assert offering == ['"reset_execute", "statistics"']


async def test_statistics_survive_reload(hass: FakeHass) -> None:
    entry = await set_up(hass, {CONF_MODE: "observe"})
    bridge_of(hass).observe(text="Ist das Licht aus?", language="de")
    await hass.config_entries.async_reload(entry.entry_id)
    bridge_of(hass).observe(text="Erzähl mir einen Witz", language="de")
    assert isinstance(hass.data[STATS_KEY], RuntimeStats)
    observed = runtime_stats(hass).snapshot()["decisions"]["observe"]
    assert observed["CONTROL_FALLBACK"] == 1
    assert observed["CHAT"] == 1
