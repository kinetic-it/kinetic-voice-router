"""Minimal client for the Hermes Agent Companion API v1 (health, capabilities, inference).

The wire contract (endpoints, bearer authentication, error codes, API major 1) follows
the MIT-licensed `Codename-11/hermes-homeassistant` project; this module is a reduced,
conversation-only re-implementation. See NOTICE.

Safety properties (all covered by tests):
- the bearer token is only sent to the configured origin; redirects are never followed;
- URLs with credentials, query strings or fragments are rejected;
- requests and responses are size- and time-bounded;
- exception texts and logs never contain the token, the URL or message content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from yarl import URL

from .const import (
    API_VERSION_MAJOR,
    MAX_ERROR_BODY,
    MAX_INFERENCE_MESSAGES,
    MAX_INFERENCE_TEXT,
    MAX_JSON_RESPONSE,
)


class HermesError(Exception):
    """Base class for stable, redacted client failures."""


class InvalidUrlError(HermesError, ValueError):
    """The companion URL is unsafe or malformed."""


class CannotConnectError(HermesError):
    """The companion could not be reached in time."""


class AuthenticationError(HermesError):
    """The bearer token was missing or rejected."""


class UnsupportedApiError(HermesError):
    """The companion does not implement API major version 1."""


class CapabilityUnavailableError(HermesError):
    """The companion does not offer conversation/inference."""


class InvalidResponseError(HermesError):
    """The companion answered with an invalid or oversized payload."""


class RequestError(HermesError):
    """The request is invalid before it is sent."""


class RemoteError(HermesError):
    """A stable error code returned by the companion (no message text kept)."""

    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(f"Hermes companion returned {code} (HTTP {status})")


@dataclass(frozen=True)
class Capabilities:
    api_version: str
    companion_version: str | None
    conversation_available: bool
    languages: tuple[str, ...]


def normalize_url(value: str) -> str:
    """Validate a companion base URL and strip a trailing slash."""
    try:
        url = URL(value.strip())
    except (AttributeError, TypeError, ValueError) as err:
        raise InvalidUrlError("Enter a valid HTTP or HTTPS URL") from err
    if url.scheme not in {"http", "https"} or not url.host:
        raise InvalidUrlError("Enter an HTTP or HTTPS URL with a host")
    if url.user is not None or url.password is not None:
        raise InvalidUrlError("Embedded URL credentials are not allowed")
    if url.fragment:
        raise InvalidUrlError("URL fragments are not allowed")
    if url.query_string:
        raise InvalidUrlError("URL query strings are not allowed")
    return str(url.with_path(url.path.rstrip("/")).with_query(None).with_fragment(None))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


class HermesClient:
    """Uses Home Assistant's shared aiohttp session (passed in)."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        token: str,
        *,
        request_timeout: float = 10.0,
        inference_timeout: float = 60.0,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationError("A bearer token is required")
        self._session = session
        self._base = URL(normalize_url(base_url))
        self._headers = {"Authorization": f"Bearer {token.strip()}"}
        self._request_timeout = request_timeout
        self._inference_timeout = inference_timeout

    async def async_health(self) -> str:
        """Liveness check. Returns the reported status text."""
        data = await self._request_json("GET", "/health", self._request_timeout)
        status = data.get("status")
        if not isinstance(status, str) or not status:
            raise InvalidResponseError("Health response has no status")
        return status

    async def async_capabilities(self) -> Capabilities:
        """Fetch and validate the capability document (API major 1)."""
        data = await self._request_json("GET", "/v1/capabilities", self._request_timeout)
        version = data.get("api_version")
        version_text = str(version) if isinstance(version, (str, int)) else ""
        try:
            major = int(version_text.removeprefix("v").removeprefix("V").split(".", 1)[0])
        except ValueError:
            major = -1
        if major != API_VERSION_MAJOR:
            raise UnsupportedApiError("Unsupported companion API version")
        raw = data.get("capabilities", data.get("platforms", {}))
        if not isinstance(raw, Mapping):
            raise InvalidResponseError("Capabilities response has no platform map")
        conversation_info = raw.get("conversation")
        return Capabilities(
            api_version=version_text,
            companion_version=_optional_string(data.get("companion_version")),
            conversation_available=_conversation_enabled(raw),
            languages=_strings(
                conversation_info.get("languages")
                if isinstance(conversation_info, Mapping)
                else None
            ),
        )

    async def async_inference(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        conversation_id: str | None = None,
        language: str | None = None,
    ) -> str:
        """Run one conversation turn and return the answer text (never empty)."""
        serialized: list[dict[str, str]] = []
        for message in messages[-MAX_INFERENCE_MESSAGES:]:
            role, content = message.get("role"), message.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise RequestError("Inference messages require a valid role and string content")
            serialized.append({"role": role, "content": content[:MAX_INFERENCE_TEXT]})
        if not serialized:
            raise RequestError("At least one inference message is required")
        payload: dict[str, Any] = {"messages": serialized}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if language:
            payload["language"] = language
        data = await self._request_json(
            "POST", "/v1/inference", self._inference_timeout, json_data=payload
        )
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise InvalidResponseError("Inference response has no text")
        return text.strip()

    async def _request_json(
        self,
        method: str,
        path: str,
        time_limit: float,
        *,
        json_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self._base.with_path(f"{self._base.path.rstrip('/')}{path}")
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers,
                json=json_data,
                timeout=ClientTimeout(total=time_limit),
                # No redirect is followed: the token can never leave the configured origin.
                allow_redirects=False,
            ) as response:
                await _raise_for_error(response)
                raw = await _read_bounded(response, MAX_JSON_RESPONSE)
        except (TimeoutError, ClientError) as err:
            raise CannotConnectError("Unable to reach the Hermes companion") from err
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise InvalidResponseError("Companion returned invalid JSON") from err
        if not isinstance(parsed, dict):
            raise InvalidResponseError("Companion returned a non-object JSON response")
        return parsed


def _conversation_enabled(capabilities: Mapping[str, Any]) -> bool:
    """True only if conversation or inference is explicitly offered."""
    for name in ("conversation", "inference"):
        value = capabilities.get(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, Mapping):
            enabled = value.get("available", value.get("enabled", True))
            if isinstance(enabled, bool):
                return enabled
    return False


async def _raise_for_error(response: ClientResponse) -> None:
    if response.status < 300:
        return
    raw = await _read_bounded(response, MAX_ERROR_BODY, truncate=True)
    code = "http_error"
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            error = payload.get("error", payload)
            if isinstance(error, dict):
                code = _optional_string(error.get("code")) or code
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    if response.status in {401, 403} or code == "unauthorized":
        raise AuthenticationError("The Hermes companion rejected the token")
    if 300 <= response.status < 400:
        raise RemoteError("redirect_refused", response.status)
    if code == "capability_unavailable":
        raise CapabilityUnavailableError("Capability unavailable")
    raise RemoteError(code, response.status)


async def _read_bounded(response: ClientResponse, limit: int, *, truncate: bool = False) -> bytes:
    length = response.content_length
    if length is not None and length > limit and not truncate:
        raise InvalidResponseError("Companion response exceeds the safe size limit")
    raw = bytearray()
    while chunk := await response.content.read(min(65536, limit + 1 - len(raw))):
        raw.extend(chunk)
        if len(raw) > limit:
            if truncate:
                return bytes(raw[:limit])
            raise InvalidResponseError("Companion response exceeds the safe size limit")
    return bytes(raw)
