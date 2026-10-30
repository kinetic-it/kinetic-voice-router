"""Home Assistant contract stubs and a fake Hermes Companion for the integration tests.

The stubs model the parts of Home Assistant Core 2026.9 the integration relies on:
config entry lifecycle (migration before setup, setup incl. ConfigEntryAuthFailed /
ConfigEntryNotReady, platform forwarding, unload with on_unload callbacks, reload,
update listeners), config/options flow results incl. menus, reauth/reconfigure
helpers, selectors, `hass.data`, the conversation entity base and the intent
response classes. These are CONTRACT STUBS, not a real Home Assistant: green tests
here are not a live Home Assistant result.

The Hermes Companion is a real local aiohttp server (no external network), so the
real `HermesClient` is exercised end to end.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "test-token-1234567890"  # noqa: S105 - synthetic test credential


def _module(name: str) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


custom_components = _module("custom_components")
custom_components.__path__ = [str(ROOT / "custom_components")]
homeassistant = _module("homeassistant")
components = _module("homeassistant.components")
conversation = _module("homeassistant.components.conversation")
config_entries = _module("homeassistant.config_entries")
const = _module("homeassistant.const")
core = _module("homeassistant.core")
exceptions = _module("homeassistant.exceptions")
helpers = _module("homeassistant.helpers")
selector = _module("homeassistant.helpers.selector")
intent = _module("homeassistant.helpers.intent")
entity_platform = _module("homeassistant.helpers.entity_platform")
aiohttp_client = _module("homeassistant.helpers.aiohttp_client")
for _name, _mod in {
    "components": components,
    "config_entries": config_entries,
    "const": const,
    "core": core,
    "exceptions": exceptions,
    "helpers": helpers,
}.items():
    setattr(homeassistant, _name, _mod)
components.conversation = conversation
for _name, _mod in {
    "selector": selector,
    "intent": intent,
    "entity_platform": entity_platform,
    "aiohttp_client": aiohttp_client,
}.items():
    setattr(helpers, _name, _mod)


# --- const / exceptions / core ----------------------------------------------------------


class Platform(StrEnum):
    CONVERSATION = "conversation"


const.Platform = Platform
const.MATCH_ALL = "*"
core.callback = lambda func: func
entity_platform.AddConfigEntryEntitiesCallback = object


class HomeAssistant:
    """Typing placeholder; tests use FakeHass."""


core.HomeAssistant = HomeAssistant


class HomeAssistantError(Exception):
    pass


class ConfigEntryError(HomeAssistantError):
    pass


class ConfigEntryNotReady(HomeAssistantError):
    pass


class ConfigEntryAuthFailed(HomeAssistantError):
    pass


exceptions.HomeAssistantError = HomeAssistantError
exceptions.ConfigEntryError = ConfigEntryError
exceptions.ConfigEntryNotReady = ConfigEntryNotReady
exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed


# --- selectors --------------------------------------------------------------------------


class SelectSelectorMode(StrEnum):
    LIST = "list"
    DROPDOWN = "dropdown"


class SelectSelector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def __call__(self, value: Any) -> Any:
        if value not in self.config["options"]:
            raise ValueError("invalid option")
        return value


class TextSelectorType(StrEnum):
    TEXT = "text"
    URL = "url"
    PASSWORD = "password"  # noqa: S105 - selector type name


class TextSelector:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def __call__(self, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("not a string")
        return value


class BooleanSelector:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def __call__(self, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("not a bool")
        return value


selector.SelectSelectorMode = SelectSelectorMode
selector.SelectSelectorConfig = dict
selector.SelectSelector = SelectSelector
selector.TextSelectorType = TextSelectorType


def _text_config(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


selector.TextSelectorConfig = _text_config
selector.TextSelector = TextSelector
selector.BooleanSelector = BooleanSelector


# --- config entries and flows -----------------------------------------------------------


class ConfigEntryState(Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    SETUP_ERROR = "setup_error"
    SETUP_RETRY = "setup_retry"
    MIGRATION_ERROR = "migration_error"


class ConfigEntry:
    def __class_getitem__(cls, item: Any) -> type[ConfigEntry]:
        return cls

    def __init__(
        self,
        *,
        domain: str,
        entry_id: str,
        title: str = "",
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        state: ConfigEntryState = ConfigEntryState.NOT_LOADED,
        version: int = 1,
        minor_version: int = 1,
    ) -> None:
        self.version = version
        self.minor_version = minor_version
        self.domain = domain
        self.entry_id = entry_id
        self.title = title
        self.data = MappingProxyType(dict(data or {}))
        self.options = MappingProxyType(dict(options or {}))
        self.state = state
        self.runtime_data: Any = None
        self.reauth_started = False
        self.update_listeners: list[Callable[[Any, ConfigEntry], Awaitable[None]]] = []
        self._on_unload: list[Callable[[], None]] = []

    def add_update_listener(
        self, listener: Callable[[Any, ConfigEntry], Awaitable[None]]
    ) -> Callable[[], None]:
        self.update_listeners.append(listener)
        return lambda: self.update_listeners.remove(listener)

    def async_on_unload(self, func: Callable[[], None]) -> None:
        self._on_unload.append(func)


class FlowBase:
    handler: str
    hass: Any

    def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}

    def async_abort(self, *, reason: str) -> dict[str, Any]:
        return {"type": "abort", "reason": reason}

    def async_show_menu(
        self,
        *,
        step_id: str,
        menu_options: list[str],
        description_placeholders: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "menu",
            "step_id": step_id,
            "menu_options": menu_options,
            "description_placeholders": description_placeholders,
        }


class ConfigFlow(FlowBase):
    _entry: ConfigEntry | None = None

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.handler = domain

    def _async_current_entries(self, include_ignore: bool | None = None) -> list[ConfigEntry]:
        return self.hass.config_entries.async_entries(self.handler)

    def _get_reauth_entry(self) -> ConfigEntry:
        assert self._entry is not None
        return self._entry

    def _get_reconfigure_entry(self) -> ConfigEntry:
        assert self._entry is not None
        return self._entry

    def async_create_entry(
        self,
        *,
        title: str,
        data: dict[str, Any],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"type": "create_entry", "title": title, "data": data, "options": options or {}}

    def async_update_reload_and_abort(
        self,
        entry: ConfigEntry,
        *,
        data_updates: dict[str, Any] | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        entry.data = MappingProxyType({**entry.data, **(data_updates or {})})
        self.hass.reload_requests.append(entry.entry_id)
        return {"type": "abort", "reason": reason or "reauth_successful"}


class OptionsFlow(FlowBase):
    config_entry: ConfigEntry

    def async_create_entry(
        self, *, title: str | None = None, data: dict[str, Any]
    ) -> dict[str, Any]:
        return {"type": "create_entry", "data": data}


for _name, _value in {
    "ConfigEntry": ConfigEntry,
    "ConfigEntryState": ConfigEntryState,
    "ConfigFlow": ConfigFlow,
    "ConfigFlowResult": dict[str, Any],
    "OptionsFlow": OptionsFlow,
}.items():
    setattr(config_entries, _name, _value)


# --- conversation / intent --------------------------------------------------------------


class IntentResponseErrorCode(StrEnum):
    FAILED_TO_HANDLE = "failed_to_handle"


class IntentResponse:
    def __init__(self, language: str) -> None:
        self.language = language
        self.speech: str | None = None
        self.error_code: IntentResponseErrorCode | None = None

    def async_set_speech(self, speech: str) -> None:
        self.speech = speech

    def async_set_error(self, code: IntentResponseErrorCode, message: str) -> None:
        self.error_code = code
        self.speech = message


intent.IntentResponse = IntentResponse
intent.IntentResponseErrorCode = IntentResponseErrorCode


@dataclass
class ConversationInput:
    text: str
    conversation_id: str | None
    language: str
    agent_id: str = "conversation.kinetic_voice_router"


@dataclass
class ConversationResult:
    response: IntentResponse
    conversation_id: str | None = None


@dataclass(frozen=True)
class SystemContent:
    content: str
    role: str = "system"


@dataclass(frozen=True)
class UserContent:
    content: str
    role: str = "user"


@dataclass(frozen=True)
class AssistantContent:
    agent_id: str
    content: str | None = None
    role: str = "assistant"


class ChatLog:
    def __init__(self, content: list[object] | None = None, conversation_id: str = "session-1"):
        self.content = content or [SystemContent("")]
        self.conversation_id = conversation_id

    def async_add_assistant_content_without_tools(self, content: AssistantContent) -> None:
        self.content.append(content)


class ConversationEntity:
    hass: Any
    entity_id: str | None = None

    async def async_added_to_hass(self) -> None:
        return None

    async def async_will_remove_from_hass(self) -> None:
        return None

    async def async_process(
        self, user_input: ConversationInput, chat_log: ChatLog | None = None
    ) -> ConversationResult:
        log = chat_log or ChatLog()
        log.content.append(UserContent(user_input.text))
        return await self._async_handle_message(user_input, log)

    async def _async_handle_message(
        self, user_input: ConversationInput, chat_log: ChatLog
    ) -> ConversationResult:
        raise NotImplementedError


def async_get_result_from_chat_log(
    user_input: ConversationInput, chat_log: ChatLog
) -> ConversationResult:
    response = IntentResponse(user_input.language)
    response.async_set_speech(chat_log.content[-1].content)
    return ConversationResult(response, user_input.conversation_id)


def async_set_agent(hass: Any, entry: Any, agent: Any) -> None:
    hass.data.setdefault("conversation_agents", {})[entry.entry_id] = agent


def async_unset_agent(hass: Any, entry: Any) -> None:
    hass.data.get("conversation_agents", {}).pop(entry.entry_id, None)


for _name, _value in {
    "ConversationEntity": ConversationEntity,
    "ConversationInput": ConversationInput,
    "ConversationResult": ConversationResult,
    "ChatLog": ChatLog,
    "SystemContent": SystemContent,
    "UserContent": UserContent,
    "AssistantContent": AssistantContent,
    "async_get_result_from_chat_log": async_get_result_from_chat_log,
    "async_set_agent": async_set_agent,
    "async_unset_agent": async_unset_agent,
}.items():
    setattr(conversation, _name, _value)


# --- hass -------------------------------------------------------------------------------


class FakeConfigEntries:
    """Lifecycle manager modelled on homeassistant.config_entries.ConfigEntries."""

    def __init__(self, hass: FakeHass) -> None:
        self.hass = hass
        self._entries: dict[str, ConfigEntry] = {}

    def async_entries(self, domain: str | None = None) -> list[ConfigEntry]:
        return [e for e in self._entries.values() if domain is None or e.domain == domain]

    def add(self, entry: ConfigEntry) -> ConfigEntry:
        self._entries[entry.entry_id] = entry
        return entry

    def _integration(self, entry: ConfigEntry) -> Any:
        return importlib.import_module(f"custom_components.{entry.domain}")

    async def async_setup(self, entry_id: str) -> bool:
        entry = self._entries[entry_id]
        integration = self._integration(entry)
        flow = importlib.import_module(f"custom_components.{entry.domain}.config_flow")
        handler = next(
            cls
            for cls in vars(flow).values()
            if isinstance(cls, type) and getattr(cls, "handler", None) == entry.domain
        )
        # Mirrors ConfigEntry.async_migrate (HA Core 2026.9.4, config_entries.py):
        same_major = entry.version == handler.VERSION
        if not (same_major and entry.minor_version == handler.MINOR_VERSION):
            if entry.version > handler.VERSION:
                entry.state = ConfigEntryState.MIGRATION_ERROR
                return False
            migrate = getattr(integration, "async_migrate_entry", None)
            if migrate is None:
                if not same_major:
                    entry.state = ConfigEntryState.MIGRATION_ERROR
                    return False
            elif not await migrate(self.hass, entry):
                entry.state = ConfigEntryState.MIGRATION_ERROR
                return False
        try:
            ok = await integration.async_setup_entry(self.hass, entry)
        except ConfigEntryAuthFailed:
            entry.reauth_started = True
            entry.state = ConfigEntryState.SETUP_ERROR
            return False
        except ConfigEntryNotReady:
            entry.state = ConfigEntryState.SETUP_RETRY
            return False
        entry.state = ConfigEntryState.LOADED if ok else ConfigEntryState.SETUP_ERROR
        return ok

    async def async_forward_entry_setups(self, entry: ConfigEntry, platforms: list[Any]) -> None:
        for platform in platforms:
            module = importlib.import_module(f"custom_components.{entry.domain}.{platform.value}")
            added: list[Any] = []
            await module.async_setup_entry(self.hass, entry, added.extend)
            for entity in added:
                entity.hass = self.hass
                await entity.async_added_to_hass()
                self.hass.entities.setdefault(entry.entry_id, []).append(entity)

    async def async_unload_platforms(self, entry: ConfigEntry, platforms: list[Any]) -> bool:
        for entity in self.hass.entities.pop(entry.entry_id, []):
            await entity.async_will_remove_from_hass()
        return True

    async def async_unload(self, entry_id: str) -> bool:
        entry = self._entries[entry_id]
        ok = await self._integration(entry).async_unload_entry(self.hass, entry)
        if ok:
            while entry._on_unload:
                entry._on_unload.pop()()
            entry.runtime_data = None
            entry.state = ConfigEntryState.NOT_LOADED
        return ok

    async def async_reload(self, entry_id: str) -> bool:
        self.hass.reload_calls.append(entry_id)
        await self.async_unload(entry_id)
        return await self.async_setup(entry_id)

    def async_update_entry(
        self,
        entry: ConfigEntry,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        version: int | None = None,
        minor_version: int | None = None,
    ) -> bool:
        if data is not None:
            entry.data = MappingProxyType(dict(data))
        if options is not None:
            entry.options = MappingProxyType(dict(options))
        if version is not None:
            entry.version = version
        if minor_version is not None:
            entry.minor_version = minor_version
        return True

    async def async_update_options(self, entry: ConfigEntry, options: dict[str, Any]) -> None:
        """What HA does after an options flow finished: store, then notify listeners."""
        entry.options = MappingProxyType(dict(options))
        for listener in list(entry.update_listeners):
            await listener(self.hass, entry)


class FakeHass:
    def __init__(self, language: str = "de") -> None:
        self.data: dict[str, Any] = {}
        self.config = type("Config", (), {"language": language})()
        self.config_entries = FakeConfigEntries(self)
        self.reload_calls: list[str] = []
        self.reload_requests: list[str] = []
        self.entities: dict[str, list[Any]] = {}
        self.session: ClientSession | None = None
        self.companion: Any = None


def async_get_clientsession(hass: Any, verify_ssl: bool = True) -> ClientSession:
    hass.session_verify_ssl = verify_ssl
    assert hass.session is not None, "test must provide hass.session"
    return hass.session


aiohttp_client.async_get_clientsession = async_get_clientsession


# --- fake Hermes Companion (real local HTTP server) ----------------------------------


@dataclass
class FakeCompanion:
    """Behaviour switches for the local companion; records what it received."""

    token: str = TOKEN
    api_version: Any = "1.0"
    conversation: Any = True  # False / {"available": False} / missing
    languages: list[str] = field(default_factory=lambda: ["de", "en"])
    answers: list[Any] = field(default_factory=lambda: ["Die Alpen sind ein Hochgebirge."])
    health_status: int = 200
    inference_status: int = 200
    delay: float = 0.0
    redirect_to: str | None = None
    huge: bool = False
    stream_huge: bool = False
    requests: list[dict[str, Any]] = field(default_factory=list)
    auth_headers: list[str | None] = field(default_factory=list)
    inference_bodies: list[dict[str, Any]] = field(default_factory=list)
    base_url: str = ""

    def _caps(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self.conversation is not None:
            caps["conversation"] = (
                {"available": self.conversation, "languages": self.languages}
                if isinstance(self.conversation, bool)
                else self.conversation
            )
        return {"api_version": self.api_version, "companion_version": "9.9.9", "capabilities": caps}

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append({"method": request.method, "path": request.path})
        self.auth_headers.append(request.headers.get("Authorization"))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.redirect_to is not None:
            raise web.HTTPFound(self.redirect_to)
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return web.json_response({"error": {"code": "unauthorized"}}, status=401)
        if self.stream_huge:
            # chunked, no Content-Length: only the streaming bound can stop this
            stream = web.StreamResponse(headers={"Content-Type": "application/json"})
            await stream.prepare(request)
            await stream.write(b'{"text": "')
            for _ in range(40):
                await stream.write(b"x" * 65536)
            await stream.write(b'"}')
            return stream
        if self.huge:
            return web.Response(
                body=b"{" + b" " * (1024 * 1024) + b"}", content_type="application/json"
            )
        if request.path == "/health":
            return web.json_response({"status": "ok"}, status=self.health_status)
        if request.path == "/v1/capabilities":
            return web.json_response(self._caps())
        if request.path == "/v1/inference" and request.method == "POST":
            self.inference_bodies.append(await request.json())
            if self.inference_status != 200:
                return web.json_response(
                    {"error": {"code": "provider_error", "message": "secret detail"}},
                    status=self.inference_status,
                )
            answer = self.answers[0] if len(self.answers) == 1 else self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return web.json_response({"text": answer})
        return web.json_response({"error": {"code": "not_found"}}, status=404)


@pytest.fixture
async def companion():
    state = FakeCompanion()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", state.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    state.base_url = str(server.make_url("")).rstrip("/")
    try:
        yield state
    finally:
        await server.close()


@pytest.fixture
async def session():
    async with ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def hass(session: ClientSession, companion: FakeCompanion) -> FakeHass:
    fake = FakeHass()
    fake.session = session
    fake.companion = companion
    return fake
