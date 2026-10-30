"""Real connection status for the Hermes Agent Companion (no guessing, no secrets).

A status is only ever the result of an actual probe or of an actual conversation
call. Nothing here stores URLs, tokens, message content or conversation IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    CONN_AUTH_FAILED,
    CONN_INVALID_RESPONSE,
    CONN_NO_CONVERSATION,
    CONN_NOT_CONFIGURED,
    CONN_OK,
    CONN_UNKNOWN,
    CONN_UNREACHABLE,
    CONN_UNSUPPORTED_API,
)
from .hermes_client import (
    AuthenticationError,
    CannotConnectError,
    CapabilityUnavailableError,
    HermesClient,
    HermesError,
    InvalidResponseError,
    RemoteError,
    UnsupportedApiError,
)
from .texts import language

_LABELS: dict[str, dict[str, str]] = {
    "de": {
        CONN_OK: "Hermes Companion erreichbar und kompatibel",
        CONN_UNREACHABLE: "Hermes Companion nicht erreichbar",
        CONN_AUTH_FAILED: "Hermes Companion lehnt den Token ab",
        CONN_UNSUPPORTED_API: "Hermes Companion: inkompatible API-Version",
        CONN_NO_CONVERSATION: "Hermes Companion bietet keine Gespräche an",
        CONN_INVALID_RESPONSE: "Hermes Companion: ungültige Antwort",
        CONN_UNKNOWN: "Hermes Companion: Fehler",
        CONN_NOT_CONFIGURED: "Hermes Companion nicht eingerichtet",
    },
    "en": {
        CONN_OK: "Hermes Companion reachable and compatible",
        CONN_UNREACHABLE: "Hermes Companion not reachable",
        CONN_AUTH_FAILED: "Hermes Companion rejects the token",
        CONN_UNSUPPORTED_API: "Hermes Companion: incompatible API version",
        CONN_NO_CONVERSATION: "Hermes Companion does not offer conversation",
        CONN_INVALID_RESPONSE: "Hermes Companion: invalid response",
        CONN_UNKNOWN: "Hermes Companion: error",
        CONN_NOT_CONFIGURED: "Hermes Companion not set up",
    },
}


@dataclass
class ConnectionState:
    """Last real observation. `code` is one of the CONN_* constants."""

    code: str = CONN_NOT_CONFIGURED
    api_version: str | None = None
    companion_version: str | None = None
    languages: tuple[str, ...] = ()


def code_for_error(err: BaseException) -> str:
    """Map a client failure to a status code. Unknown errors are never called 'ok'."""
    if isinstance(err, AuthenticationError):
        return CONN_AUTH_FAILED
    if isinstance(err, CannotConnectError):
        return CONN_UNREACHABLE
    if isinstance(err, UnsupportedApiError):
        return CONN_UNSUPPORTED_API
    if isinstance(err, CapabilityUnavailableError):
        return CONN_NO_CONVERSATION
    if isinstance(err, InvalidResponseError):
        return CONN_INVALID_RESPONSE
    if isinstance(err, (RemoteError, HermesError)):
        return CONN_UNKNOWN
    return CONN_UNKNOWN


async def async_probe(client: HermesClient) -> ConnectionState:
    """Health + capabilities. Succeeds only if the companion offers conversation."""
    try:
        await client.async_health()
        capabilities = await client.async_capabilities()
    except HermesError as err:
        return ConnectionState(code=code_for_error(err))
    if not capabilities.conversation_available:
        return ConnectionState(
            code=CONN_NO_CONVERSATION,
            api_version=capabilities.api_version,
            companion_version=capabilities.companion_version,
        )
    return ConnectionState(
        code=CONN_OK,
        api_version=capabilities.api_version,
        companion_version=capabilities.companion_version,
        languages=capabilities.languages,
    )


def connection_label(hass: Any, code: str) -> str:
    return _LABELS[language(hass)].get(code, code)
