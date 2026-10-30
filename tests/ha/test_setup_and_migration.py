"""Entry lifecycle: setup outcomes, migration from every earlier version, reload, unload."""

from __future__ import annotations

import pytest
from conftest import TOKEN, ConfigEntry, ConfigEntryState, FakeCompanion, FakeHass

from custom_components.kinetic_voice_router import runtime_stats
from custom_components.kinetic_voice_router.const import (
    CONF_MODE,
    CONF_ROUTER_ENABLED,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
)
from custom_components.kinetic_voice_router.voice_router import OperatingMode


def make_entry(
    hass: FakeHass,
    *,
    options: dict | None = None,
    data: dict | None = None,
    minor_version: int = 3,
    version: int = 1,
) -> ConfigEntry:
    if data is None:
        data = {
            CONF_URL: hass.companion.base_url,
            CONF_TOKEN: TOKEN,
            CONF_VERIFY_TLS: True,
        }
    return hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            title="Kinetic Voice Router",
            data=data,
            options={CONF_MODE: "off"} if options is None else options,
            minor_version=minor_version,
            version=version,
        )
    )


def agents(hass: FakeHass) -> dict:
    return hass.data.get("conversation_agents", {})


# --- Setup outcomes ----------------------------------------------------------------------


async def test_setup_registers_exactly_one_conversation_agent(hass: FakeHass):
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    entities = hass.entities[entry.entry_id]
    assert len(entities) == 1
    assert entities[0]._attr_unique_id == "kvr-1-conversation"
    assert agents(hass) == {"kvr-1": entities[0]}
    assert entry.runtime_data.connection.code == "ok"


async def test_setup_does_not_publish_a_hass_data_bridge(hass: FakeHass):
    """The legacy coupling through hass.data is gone: nothing a patched Hermes could pick up."""
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert DOMAIN not in hass.data


async def test_rejected_token_starts_reauth(hass: FakeHass, companion: FakeCompanion):
    companion.token = "something-else"  # noqa: S105
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.reauth_started is True
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not hass.entities and not agents(hass)


@pytest.mark.parametrize(
    "setup",
    [
        lambda c: setattr(c, "health_status", 503),
        lambda c: setattr(c, "api_version", "9.0"),
        lambda c: setattr(c, "conversation", False),
        lambda c: setattr(c, "huge", True),
    ],
)
async def test_unusable_companion_is_retried_without_agent(hass, companion, setup):
    setup(companion)
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.reauth_started is False
    assert not hass.entities


async def test_unreachable_companion_is_retried(hass: FakeHass):
    entry = make_entry(
        hass, data={CONF_URL: "http://127.0.0.1:9", CONF_TOKEN: TOKEN, CONF_VERIFY_TLS: True}
    )
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_invalid_stored_url_asks_for_reauth_instead_of_connecting(hass, companion):
    entry = make_entry(hass, data={CONF_URL: "file:///etc/passwd", CONF_TOKEN: TOKEN})
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.reauth_started is True
    assert companion.requests == []


# --- Migration -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old_options", "expected"),
    [
        ({CONF_ROUTER_ENABLED: True}, "active"),
        ({CONF_ROUTER_ENABLED: False}, "off"),
        ({}, "off"),
        ({CONF_ROUTER_ENABLED: "true"}, "off"),
        ({CONF_ROUTER_ENABLED: 1}, "off"),
        ({CONF_ROUTER_ENABLED: None}, "off"),
    ],
)
async def test_upgrade_from_030_keeps_state_and_never_enables(hass, old_options, expected):
    """Entry 1.1 (0.3.0, boolean router_enabled) -> 1.3, with connection data supplied."""
    entry = make_entry(hass, options=old_options, minor_version=1)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert (entry.version, entry.minor_version) == (1, 3)
    assert entry.options == {CONF_MODE: expected}
    assert entry.runtime_data.bridge.mode.value == expected
    assert entry.runtime_data.bridge.enabled is (expected == "active")


@pytest.mark.parametrize("mode", ["off", "observe", "active"])
async def test_installed_042_entry_keeps_mode_and_asks_for_the_connection(hass, mode):
    """The owner's R3.2 entry: data == {}, options {mode}, entry 1.2."""
    entry = make_entry(hass, options={CONF_MODE: mode}, data={}, minor_version=2)
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert (entry.version, entry.minor_version) == (1, 3)  # migrated before setup
    assert entry.options == {CONF_MODE: mode}  # the chosen mode survives the update
    assert entry.reauth_started is True  # asks for URL + token, guesses nothing
    assert dict(entry.data) == {}
    assert not hass.entities and not agents(hass)
    assert DOMAIN not in hass.data  # a patched hermes_agent finds no bridge: plain Hermes path


async def test_migration_runs_once(hass: FakeHass):
    entry = make_entry(hass, options={CONF_ROUTER_ENABLED: True}, minor_version=1)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.config_entries.async_update_options(entry, {CONF_MODE: "observe"})
    assert entry.options == {CONF_MODE: "observe"}
    assert entry.runtime_data.bridge.mode is OperatingMode.OBSERVE


async def test_future_major_version_is_refused(hass: FakeHass):
    entry = make_entry(hass, options={CONF_MODE: "active"}, version=2)
    assert await hass.config_entries.async_setup(entry.entry_id) is False
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


# --- Reload, unload, options ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["off", "observe", "active"])
async def test_mode_survives_reload_and_restart(hass: FakeHass, mode: str):
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.config_entries.async_update_options(entry, {CONF_MODE: mode})
    assert entry.runtime_data.bridge.mode.value == mode
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.bridge.mode.value == mode


async def test_reload_never_duplicates_the_agent(hass: FakeHass):
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    for _ in range(3):
        await hass.config_entries.async_reload(entry.entry_id)
    assert len(hass.entities[entry.entry_id]) == 1
    assert list(agents(hass)) == ["kvr-1"]


async def test_unload_removes_agent_and_listeners(hass: FakeHass):
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not agents(hass) and not hass.entities
    assert entry.update_listeners == []
    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize("stored", [None, "Aktiv", 1, True, "", ["active"]])
async def test_broken_stored_mode_fails_closed(hass: FakeHass, stored: object):
    entry = make_entry(hass, options={CONF_MODE: stored})
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.runtime_data.bridge.mode is OperatingMode.OFF


async def test_statistics_survive_reload(hass: FakeHass):
    entry = make_entry(hass, options={CONF_MODE: "observe"})
    await hass.config_entries.async_setup(entry.entry_id)
    entry.runtime_data.bridge.observe(text="Ist das Licht aus?", language="de")
    await hass.config_entries.async_reload(entry.entry_id)
    assert runtime_stats(hass).snapshot()["decisions"]["observe"]["CONTROL_FALLBACK"] == 1
