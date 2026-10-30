"""Setup, re-authentication and reconfiguration flows with a real connection test."""

from __future__ import annotations

import pytest
import voluptuous as vol
from conftest import TOKEN, ConfigEntry, FakeCompanion, FakeHass

from custom_components.kinetic_voice_router.config_flow import KineticVoiceRouterConfigFlow
from custom_components.kinetic_voice_router.const import (
    CONF_MODE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DOMAIN,
    INTEGRATION_VERSION,
)


def flow_for(hass: FakeHass, entry: ConfigEntry | None = None) -> KineticVoiceRouterConfigFlow:
    flow = KineticVoiceRouterConfigFlow()
    flow.hass = hass
    flow._entry = entry
    return flow


def good_input(companion: FakeCompanion, **overrides) -> dict:
    return {
        CONF_URL: companion.base_url,
        CONF_TOKEN: TOKEN,
        CONF_VERIFY_TLS: True,
    } | overrides


def validated(form: dict, user_input: dict) -> dict:
    """What Home Assistant does before calling the step: validate against the schema."""
    return form["data_schema"](user_input)


async def test_form_asks_for_url_token_and_tls_check(hass: FakeHass):
    form = await flow_for(hass).async_step_user()
    assert form["type"] == "form" and form["step_id"] == "user"
    assert form["errors"] == {}
    assert form["description_placeholders"] == {"version": INTEGRATION_VERSION}
    keys = {str(marker): marker for marker in form["data_schema"].schema}
    assert set(keys) == {CONF_URL, CONF_TOKEN, CONF_VERIFY_TLS}
    assert form["data_schema"].schema[keys[CONF_TOKEN]].config["type"] == "password"
    assert form["data_schema"].schema[keys[CONF_URL]].config["type"] == "url"
    assert keys[CONF_VERIFY_TLS].default() is True


async def test_valid_connection_creates_entry_in_mode_off(hass: FakeHass, companion: FakeCompanion):
    flow = flow_for(hass)
    form = await flow.async_step_user()
    result = await flow.async_step_user(validated(form, good_input(companion)))
    assert result["type"] == "create_entry"
    assert result["title"] == "Kinetic Voice Router"
    assert result["data"] == {
        CONF_URL: companion.base_url,
        CONF_TOKEN: TOKEN,
        CONF_VERIFY_TLS: True,
    }
    assert result["options"] == {CONF_MODE: "off"}
    assert (KineticVoiceRouterConfigFlow.VERSION, KineticVoiceRouterConfigFlow.MINOR_VERSION) == (
        1,
        3,
    )
    assert [r["path"] for r in companion.requests] == ["/health", "/v1/capabilities"]


async def test_url_is_normalised_before_storing(hass: FakeHass, companion: FakeCompanion):
    result = await flow_for(hass).async_step_user(
        good_input(companion, url=f"  {companion.base_url}/  ")
    )
    assert result["data"][CONF_URL] == companion.base_url


async def test_tls_setting_is_passed_to_the_http_session(hass: FakeHass, companion: FakeCompanion):
    await flow_for(hass).async_step_user(good_input(companion, verify_tls=False))
    assert hass.session_verify_ssl is False
    await flow_for(hass).async_step_user(good_input(companion, verify_tls=True))
    assert hass.session_verify_ssl is True


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"url": "ftp://host"}, "invalid_url"),
        ({"url": "http://user:pw@host"}, "invalid_url"),
        ({"url": "http://host/?token=x"}, "invalid_url"),
        ({"url": "not a url"}, "invalid_url"),
        ({"token": ""}, "invalid_auth"),
        ({"token": "wrong-token"}, "invalid_auth"),
    ],
)
async def test_bad_input_shows_error_and_creates_nothing(
    hass: FakeHass, companion: FakeCompanion, change: dict, error: str
):
    flow = flow_for(hass)
    result = await flow.async_step_user(good_input(companion, **change))
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}
    # the form is shown again with the URL the user typed; the token is never echoed
    assert TOKEN not in repr(result)
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize(
    ("setup", "error"),
    [
        (lambda c: setattr(c, "api_version", "2.0"), "unsupported_api"),
        (lambda c: setattr(c, "conversation", False), "no_conversation"),
        (lambda c: setattr(c, "conversation", None), "no_conversation"),
        (lambda c: setattr(c, "huge", True), "invalid_response"),
        (lambda c: setattr(c, "health_status", 500), "unknown"),
    ],
)
async def test_incompatible_companion_is_reported_not_saved(
    hass: FakeHass, companion: FakeCompanion, setup, error: str
):
    setup(companion)
    result = await flow_for(hass).async_step_user(good_input(companion))
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}


async def test_unreachable_companion_is_cannot_connect(hass: FakeHass):
    result = await flow_for(hass).async_step_user(
        {CONF_URL: "http://127.0.0.1:9", CONF_TOKEN: TOKEN, CONF_VERIFY_TLS: True}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert "127.0.0.1" not in str(result["errors"])


async def test_only_one_entry_allowed(hass: FakeHass, companion: FakeCompanion):
    hass.config_entries.add(ConfigEntry(domain=DOMAIN, entry_id="a", minor_version=3))
    assert await flow_for(hass).async_step_user(good_input(companion)) == {
        "type": "abort",
        "reason": "single_instance_allowed",
    }
    assert companion.requests == []  # not even a connection attempt


# --- Re-authentication (rejected token, or an upgraded entry without connection) ----------


def entry_with(hass: FakeHass, **data) -> ConfigEntry:
    return hass.config_entries.add(
        ConfigEntry(
            domain=DOMAIN,
            entry_id="kvr-1",
            data=data,
            options={CONF_MODE: "active"},
            minor_version=3,
        )
    )


async def test_reauth_updates_token_and_reloads(hass: FakeHass, companion: FakeCompanion):
    entry = entry_with(hass, url=companion.base_url, token="old-token", verify_tls=True)  # noqa: S106
    flow = flow_for(hass, entry)
    form = await flow.async_step_reauth(entry.data)
    assert form["step_id"] == "reauth_confirm"
    assert str(next(iter(form["data_schema"].schema))) == CONF_URL
    result = await flow.async_step_reauth_confirm(good_input(companion))
    assert result == {"type": "abort", "reason": "reauth_successful"}
    assert entry.data[CONF_TOKEN] == TOKEN
    assert entry.options == {CONF_MODE: "active"}  # the chosen mode is never touched
    assert hass.reload_requests == ["kvr-1"]


async def test_reauth_for_upgraded_entry_without_connection(
    hass: FakeHass, companion: FakeCompanion
):
    entry = entry_with(hass)  # 0.4.x entry: data == {}
    flow = flow_for(hass, entry)
    form = await flow.async_step_reauth_confirm()
    default_url = next(m for m in form["data_schema"].schema if str(m) == CONF_URL).default()
    assert default_url == ""
    result = await flow.async_step_reauth_confirm(good_input(companion))
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_URL] == companion.base_url
    assert entry.options == {CONF_MODE: "active"}


async def test_reauth_wrong_token_keeps_old_data(hass: FakeHass, companion: FakeCompanion):
    entry = entry_with(hass, url=companion.base_url, token="old-token", verify_tls=True)  # noqa: S106
    result = await flow_for(hass, entry).async_step_reauth_confirm(
        good_input(companion, token="still-wrong")  # noqa: S106
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_TOKEN] == "old-token"  # noqa: S105
    assert hass.reload_requests == []


# --- Reconfiguration ---------------------------------------------------------------------


async def test_reconfigure_keeps_stored_token_when_left_empty(
    hass: FakeHass, companion: FakeCompanion
):
    entry = entry_with(hass, url="http://127.0.0.1:9", token=TOKEN, verify_tls=True)
    flow = flow_for(hass, entry)
    form = await flow.async_step_reconfigure()
    token_marker = next(m for m in form["data_schema"].schema if str(m) == CONF_TOKEN)
    assert isinstance(token_marker, vol.Optional)
    result = await flow.async_step_reconfigure(
        {CONF_URL: companion.base_url, CONF_TOKEN: "", CONF_VERIFY_TLS: False}
    )
    assert result["type"] == "abort"
    assert dict(entry.data) == {
        CONF_URL: companion.base_url,
        CONF_TOKEN: TOKEN,
        CONF_VERIFY_TLS: False,
    }


async def test_reconfigure_unreachable_target_changes_nothing(
    hass: FakeHass, companion: FakeCompanion
):
    entry = entry_with(hass, url=companion.base_url, token=TOKEN, verify_tls=True)
    result = await flow_for(hass, entry).async_step_reconfigure(
        {CONF_URL: "http://127.0.0.1:9", CONF_TOKEN: "", CONF_VERIFY_TLS: True}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_URL] == companion.base_url
    assert hass.reload_requests == []
