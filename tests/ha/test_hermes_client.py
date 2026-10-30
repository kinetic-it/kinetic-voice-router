"""Hermes Companion client against a real local HTTP server (no external network)."""

from __future__ import annotations

import logging

import pytest
from aiohttp import ClientSession
from conftest import TOKEN, FakeCompanion

from custom_components.kinetic_voice_router.hermes_client import (
    AuthenticationError,
    CannotConnectError,
    HermesClient,
    InvalidResponseError,
    InvalidUrlError,
    RemoteError,
    RequestError,
    UnsupportedApiError,
    normalize_url,
)


def client(companion: FakeCompanion, session: ClientSession, **kwargs) -> HermesClient:
    return HermesClient(session, companion.base_url, kwargs.pop("token", TOKEN), **kwargs)


async def test_health_capabilities_and_inference(companion: FakeCompanion, session: ClientSession):
    hermes = client(companion, session)
    assert await hermes.async_health() == "ok"
    caps = await hermes.async_capabilities()
    assert caps.api_version == "1.0"
    assert caps.companion_version == "9.9.9"
    assert caps.conversation_available is True
    assert caps.languages == ("de", "en")
    text = await hermes.async_inference(
        [{"role": "user", "content": "Hallo"}], conversation_id="abc", language="de"
    )
    assert text == "Die Alpen sind ein Hochgebirge."
    assert companion.inference_bodies == [
        {
            "messages": [{"role": "user", "content": "Hallo"}],
            "conversation_id": "abc",
            "language": "de",
        }
    ]
    # the token is sent as a bearer header to every endpoint, nowhere else
    assert set(companion.auth_headers) == {f"Bearer {TOKEN}"}


@pytest.mark.parametrize("version", ["1", "v1", "1.4.2", 1])
async def test_api_major_1_is_accepted(companion: FakeCompanion, session: ClientSession, version):
    companion.api_version = version
    assert (await client(companion, session).async_capabilities()).conversation_available


@pytest.mark.parametrize("version", ["2.0", "0.9", "", None, "abc", [1]])
async def test_other_api_versions_are_rejected(companion, session, version):
    companion.api_version = version
    with pytest.raises(UnsupportedApiError):
        await client(companion, session).async_capabilities()


@pytest.mark.parametrize("conversation", [False, {"available": False}, {"enabled": False}, None])
async def test_conversation_must_be_explicitly_offered(companion, session, conversation):
    companion.conversation = conversation
    assert (await client(companion, session).async_capabilities()).conversation_available is False


async def test_wrong_token_is_rejected_without_leaking_it(companion, session):
    hermes = client(companion, session, token="wrong-token-value")  # noqa: S106
    with pytest.raises(AuthenticationError) as info:
        await hermes.async_health()
    assert "wrong-token-value" not in repr(info.value)
    assert TOKEN not in repr(info.value)


async def test_empty_token_is_rejected_before_any_request(companion, session):
    for token in ("", "   "):
        with pytest.raises(AuthenticationError):
            HermesClient(session, companion.base_url, token)
    assert companion.requests == []


async def test_redirects_are_never_followed(companion, session):
    companion.redirect_to = "http://127.0.0.1:9/elsewhere"
    with pytest.raises(RemoteError) as info:
        await client(companion, session).async_health()
    assert info.value.code == "redirect_refused"
    assert [r["path"] for r in companion.requests] == ["/health"]  # target never contacted


async def test_unreachable_host_is_cannot_connect(session):
    hermes = HermesClient(session, "http://127.0.0.1:9", TOKEN, request_timeout=2)
    with pytest.raises(CannotConnectError) as info:
        await hermes.async_health()
    assert TOKEN not in repr(info.value)
    assert "127.0.0.1" not in str(info.value)


async def test_timeout_is_cannot_connect(companion, session):
    companion.delay = 1.0
    with pytest.raises(CannotConnectError) as info:
        await client(companion, session, request_timeout=0.2).async_health()
    assert isinstance(info.value.__cause__, TimeoutError)


async def test_oversized_response_is_refused(companion, session):
    companion.huge = True
    with pytest.raises(InvalidResponseError):
        await client(companion, session).async_capabilities()


async def test_oversized_streamed_response_is_cut_off(companion, session):
    """No Content-Length header: the streaming bound alone must stop the read."""
    companion.stream_huge = True
    with pytest.raises(InvalidResponseError):
        await client(companion, session).async_inference([{"role": "user", "content": "x"}])


@pytest.mark.parametrize("answer", ["", "   ", None])
async def test_empty_inference_answer_is_invalid(companion, session, answer):
    companion.answers = [answer]
    with pytest.raises(InvalidResponseError):
        await client(companion, session).async_inference([{"role": "user", "content": "x"}])


async def test_remote_error_keeps_code_not_message(companion, session):
    companion.inference_status = 502
    with pytest.raises(RemoteError) as info:
        await client(companion, session).async_inference([{"role": "user", "content": "x"}])
    assert info.value.code == "provider_error"
    assert info.value.status == 502
    assert "secret detail" not in repr(info.value)


async def test_invalid_messages_are_refused_before_sending(companion, session):
    hermes = client(companion, session)
    for messages in (
        [],
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": 5}],
        [{"role": "user"}],
    ):
        with pytest.raises(RequestError):
            await hermes.async_inference(messages)  # type: ignore[arg-type]
    assert companion.requests == []


async def test_history_and_text_are_bounded(companion, session):
    messages = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    messages[-1] = {"role": "user", "content": "x" * 100_000}
    await client(companion, session).async_inference(messages)
    sent = companion.inference_bodies[0]["messages"]
    assert len(sent) == 20
    assert len(sent[-1]["content"]) == 8 * 1024


async def test_nothing_sensitive_is_logged(companion, session, caplog):
    caplog.set_level(logging.DEBUG)
    companion.answers = ["geheime Antwort"]
    hermes = client(companion, session)
    await hermes.async_inference(
        [{"role": "user", "content": "geheimer Satz"}], conversation_id="cid-77"
    )
    dumped = caplog.text
    for secret in (TOKEN, "geheimer Satz", "geheime Antwort", "cid-77"):
        assert secret not in dumped


@pytest.mark.parametrize(
    "value",
    [
        "ftp://host:8765",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://user:pw@host:8765",
        "http://user@host:8765",
        "http://host:8765/?token=abc",
        "http://host:8765/#frag",
        "http:///nohost",
        "",
        "   ",
        "host-without-scheme:8765",
    ],
)
def test_unsafe_urls_are_rejected(value):
    with pytest.raises(InvalidUrlError):
        normalize_url(value)


def test_urls_are_normalised():
    assert normalize_url(" http://host:8765/ ") == "http://host:8765"
    assert normalize_url("https://host/base/") == "https://host/base"
    assert normalize_url("http://[::1]:8765") == "http://[::1]:8765"
