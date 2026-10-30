"""Kinetic Voice Router: a Home Assistant conversation agent in front of Hermes Agent.

The integration registers its own conversation agent. Home Assistant resolves local
intents first (`prefer_local_intents`); only sentences it did not handle reach this
agent. The agent forwards them to a configured Hermes Agent Companion, optionally
checked by the router policy (modes off / observe / active). It never calls Home
Assistant services, never exposes entities and never changes the Assist pipeline.
"""

from __future__ import annotations

import logging
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_MODE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    CONN_AUTH_FAILED,
    CONN_OK,
    DEFAULT_VERIFY_TLS,
    INFERENCE_TIMEOUT,
    REQUEST_TIMEOUT,
    STATS_KEY,
)
from .hermes_client import HermesClient, HermesError
from .runtime import RouterRuntime
from .status import async_probe
from .voice_router import RouterBridge, RuntimeStats, operating_mode

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CONVERSATION]

KineticVoiceRouterConfigEntry: TypeAlias = ConfigEntry[RouterRuntime]


def runtime_stats(hass: HomeAssistant) -> RuntimeStats:
    """Process-lifetime counters; kept across entry reloads, reset by a HA restart."""
    stats = hass.data.get(STATS_KEY)
    if not isinstance(stats, RuntimeStats):
        stats = RuntimeStats()
        hass.data[STATS_KEY] = stats
    return stats


async def async_migrate_entry(hass: HomeAssistant, entry: KineticVoiceRouterConfigEntry) -> bool:
    """Bring entries of every earlier version to 1.3.

    1.1 (0.3.0, boolean router_enabled) -> 1.2 (mode off/observe/active): a previously
    enabled router stays active, anything else becomes off.
    1.2 -> 1.3 (standalone): the Hermes connection now lives in the entry itself. An
    entry without it is not guessed or filled in; setup asks for it via re-authentication.
    """
    if entry.version > 1:
        return False  # downgrade from a future version: refuse instead of guessing
    if entry.version == 1 and entry.minor_version < 2:
        mode = operating_mode(entry.options).value
        hass.config_entries.async_update_entry(entry, options={CONF_MODE: mode}, minor_version=2)
        _LOGGER.info("Kinetic Voice Router options migrated to mode=%s", mode)
    if entry.version == 1 and entry.minor_version < 3:
        hass.config_entries.async_update_entry(entry, minor_version=3)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KineticVoiceRouterConfigEntry) -> bool:
    """Connect to the Hermes Companion and register the conversation agent."""
    url, token = entry.data.get(CONF_URL), entry.data.get(CONF_TOKEN)
    if not url or not token:
        raise ConfigEntryAuthFailed("Hermes Companion connection is not configured")
    verify_tls = bool(entry.data.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS))
    try:
        client = HermesClient(
            async_get_clientsession(hass, verify_ssl=verify_tls),
            url,
            token,
            request_timeout=REQUEST_TIMEOUT,
            inference_timeout=INFERENCE_TIMEOUT,
        )
    except HermesError as err:
        raise ConfigEntryAuthFailed("Hermes Companion connection data is invalid") from err
    connection = await async_probe(client)
    if connection.code == CONN_AUTH_FAILED:
        raise ConfigEntryAuthFailed("Hermes Companion rejected the token")
    if connection.code != CONN_OK:
        # Not an error of this entry's data: retried by Home Assistant with back-off.
        raise ConfigEntryNotReady(f"Hermes Companion not usable ({connection.code})")
    entry.runtime_data = RouterRuntime(
        bridge=RouterBridge.from_options(entry.options, stats=runtime_stats(hass)),
        client=client,
        connection=connection,
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Kinetic Voice Router set up (mode=%s)", entry.runtime_data.bridge.mode.value)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KineticVoiceRouterConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: KineticVoiceRouterConfigEntry) -> None:
    """Options changed: reload so the new setting takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
