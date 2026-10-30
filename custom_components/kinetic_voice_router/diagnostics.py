"""Diagnostics for the Kinetic Voice Router (no speech text, IDs, URL or token)."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import KineticVoiceRouterConfigEntry, runtime_stats
from .const import (
    CONF_MODE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    DEFAULT_VERIFY_TLS,
    INTEGRATION_VERSION,
    MODES,
)
from .voice_router import ROUTER_VERSION


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: KineticVoiceRouterConfigEntry
) -> dict[str, Any]:
    """Configuration facts and process-lifetime counters only.

    The Hermes URL and token are never exported, not even in redacted form; only
    whether they are present. The session store is not exported.
    """
    runtime = getattr(entry, "runtime_data", None)
    stored = entry.options.get(CONF_MODE)
    return {
        "integration_version": INTEGRATION_VERSION,
        "router_version": ROUTER_VERSION,
        "config_entry_version": f"{entry.version}.{entry.minor_version}",
        "mode_option_valid": isinstance(stored, str) and stored in MODES,
        "mode": runtime.bridge.mode.value if runtime is not None else None,
        "hermes": {
            "url_configured": bool(entry.data.get(CONF_URL)),
            "token_configured": bool(entry.data.get(CONF_TOKEN)),
            "verify_tls": bool(entry.data.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS)),
            "status": runtime.connection.code if runtime is not None else None,
            "api_version": runtime.connection.api_version if runtime is not None else None,
            "companion_version": (
                runtime.connection.companion_version if runtime is not None else None
            ),
        },
        "runtime_statistics": runtime_stats(hass).snapshot(),
    }
