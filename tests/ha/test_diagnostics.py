"""Diagnostics export only facts and counters: no URL, token, text or IDs."""

from __future__ import annotations

from conftest import TOKEN, ConfigEntry, FakeCompanion, FakeHass

from custom_components.kinetic_voice_router import diagnostics
from custom_components.kinetic_voice_router.const import (
    CONF_MODE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
    INTEGRATION_VERSION,
)

SECRET_SENTENCE = "Ist die Staubsaugersteckdose von Familie Müller an?"


async def loaded(hass: FakeHass, mode: str = "active"):
    entry = hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            data={CONF_URL: hass.companion.base_url, CONF_TOKEN: TOKEN, CONF_VERIFY_TLS: True},
            options={CONF_MODE: mode},
            minor_version=3,
        )
    )
    await hass.config_entries.async_setup(entry.entry_id)
    return entry


async def test_diagnostics_contains_only_facts_and_counters(
    hass: FakeHass, companion: FakeCompanion
):
    entry = await loaded(hass)
    entity = hass.entities[entry.entry_id][0]
    from conftest import ChatLog, ConversationInput

    await entity.async_process(
        ConversationInput(SECRET_SENTENCE, "01J9SECRETID", "de"),
        ChatLog(conversation_id="01J9SECRETID"),
    )
    diag = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    stats = diag.pop("runtime_statistics")
    assert diag == {
        "integration_version": INTEGRATION_VERSION,
        "router_version": INTEGRATION_VERSION,
        "config_entry_version": "1.3",
        "mode_option_valid": True,
        "mode": "active",
        "hermes": {
            "url_configured": True,
            "token_configured": True,
            "verify_tls": True,
            "status": "ok",
            "api_version": "1.0",
            "companion_version": "9.9.9",
        },
    }
    assert stats["scope"] == "process_lifetime"
    assert stats["decisions"]["active"]["CONTROL_FALLBACK"] == 1
    dumped = (repr(diag) + repr(stats)).lower()
    for secret in (TOKEN, companion.base_url, "127.0.0.1", "01j9secretid", "staubsauger", "müller"):
        assert secret.lower() not in dumped


async def test_diagnostics_without_connection_data(hass: FakeHass):
    entry = hass.config_entries.add(
        ConfigEntry(domain=DOMAIN, entry_id="legacy", options={CONF_MODE: "off"}, minor_version=2)
    )
    await hass.config_entries.async_setup(entry.entry_id)  # asks for re-authentication
    diag = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert diag["mode"] is None
    assert diag["hermes"] == {
        "url_configured": False,
        "token_configured": False,
        "verify_tls": True,
        "status": None,
        "api_version": None,
        "companion_version": None,
    }


async def test_diagnostics_after_unload(hass: FakeHass):
    entry = await loaded(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    diag = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert diag["mode"] is None and diag["hermes"]["status"] is None
