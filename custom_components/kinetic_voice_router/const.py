"""Constants for the Kinetic Voice Router integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "kinetic_voice_router"
NAME: Final = "Kinetic Voice Router"
# Must match manifest.json "version" (checked by tests).
INTEGRATION_VERSION: Final = "0.5.0b3"

# Hermes Agent Companion connection (config entry data; the token is a secret).
CONF_URL: Final = "url"
CONF_TOKEN: Final = "token"  # noqa: S105 - config key, not a credential
CONF_VERIFY_TLS: Final = "verify_tls"
DEFAULT_VERIFY_TLS: Final = True
REQUEST_TIMEOUT: Final = 10.0
INFERENCE_TIMEOUT: Final = 60.0

# Companion API limits.
API_VERSION_MAJOR: Final = 1
MAX_ERROR_BODY: Final = 8 * 1024
MAX_JSON_RESPONSE: Final = 512 * 1024
MAX_INFERENCE_MESSAGES: Final = 20
MAX_INFERENCE_TEXT: Final = 8 * 1024

# Options. `mode` replaces the 0.3.0 boolean `router_enabled`.
CONF_MODE: Final = "mode"
MODE_OFF: Final = "off"
MODE_OBSERVE: Final = "observe"
MODE_ACTIVE: Final = "active"
MODES: Final = (MODE_OFF, MODE_OBSERVE, MODE_ACTIVE)
DEFAULT_MODE: Final = MODE_OFF
CONF_ROUTER_ENABLED: Final = "router_enabled"  # 0.3.0 option, migrated to `mode`

# Adaptive Speech Memory: learning switch (option, default off) and form fields.
CONF_SPEECH_MEMORY: Final = "speech_memory"
DEFAULT_SPEECH_MEMORY: Final = False
CONF_HEARD: Final = "heard"
CONF_INTENDED: Final = "intended"
CONF_CATEGORY: Final = "category"
CONF_ENTRY: Final = "entry"

# Test step field (never stored).
CONF_TEST_SENTENCE: Final = "test_sentence"

# Runtime statistics live in hass.data for the process lifetime (survive entry reloads).
STATS_KEY: Final = f"{DOMAIN}_stats"

# Connection status codes (derived from real probes, never guessed).
CONN_OK: Final = "ok"
CONN_UNREACHABLE: Final = "unreachable"
CONN_AUTH_FAILED: Final = "auth_failed"
CONN_UNSUPPORTED_API: Final = "unsupported_api"
CONN_NO_CONVERSATION: Final = "no_conversation"
CONN_INVALID_RESPONSE: Final = "invalid_response"
CONN_UNKNOWN: Final = "unknown"
CONN_NOT_CONFIGURED: Final = "not_configured"
