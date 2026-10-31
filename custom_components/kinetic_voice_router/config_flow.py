"""Config and options flow for the Kinetic Voice Router.

Setup (Settings -> Devices & services -> Add integration): Hermes Companion URL, bearer
token and a real connection test; nothing is created unless the companion answers
`/health` and `/v1/capabilities` (API major 1) and offers conversation.
Re-authentication and reconfiguration reuse the same test.

Options ("Konfigurieren") are native Home Assistant flow steps:
- settings:      operating mode off / observe / active (saved as options)
- connection:    live status of the Hermes Companion, re-test on demand
- test:          input form ("Anfrage testen") -> test_result menu with four lines
                 (simulation only, nothing stored or executed) -> new request / back
- statistics:    summary menu -> statistics_details / reset_confirm -> reset_execute
                 (process-lifetime counters; reset only after explicit confirmation)

HA forms render the description above the fields and have exactly one button,
so results get their own menu step and the reset confirmation is a menu with an
explicit cancel entry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import runtime_stats
from .const import (
    CONF_CATEGORY,
    CONF_ENTRY,
    CONF_HEARD,
    CONF_INTENDED,
    CONF_MODE,
    CONF_SPEECH_MEMORY,
    CONF_TEST_SENTENCE,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_TLS,
    CONN_AUTH_FAILED,
    CONN_INVALID_RESPONSE,
    CONN_NO_CONVERSATION,
    CONN_OK,
    CONN_UNKNOWN,
    CONN_UNREACHABLE,
    CONN_UNSUPPORTED_API,
    DEFAULT_MODE,
    DEFAULT_SPEECH_MEMORY,
    DEFAULT_VERIFY_TLS,
    DOMAIN,
    INFERENCE_TIMEOUT,
    INTEGRATION_VERSION,
    MODES,
    NAME,
    REQUEST_TIMEOUT,
)
from .hermes_client import HermesClient, HermesError, InvalidUrlError, normalize_url
from .status import ConnectionState, async_probe, connection_label
from .texts import (
    FORWARD_TO_HERMES,
    MODE_LABELS,
    REASONS,
    ROUTE_LABELS,
    language,
    speech_memory_overview,
    statistics_details,
    statistics_summary,
)
from .voice_router import ROUTER_VERSION, operating_mode, simulate
from .voice_router.speech_memory import MAX_ENTRIES, Category, Entry, Source

# Probe result -> form error key (strings.json "config.error").
_PROBE_ERRORS = {
    CONN_UNREACHABLE: "cannot_connect",
    CONN_AUTH_FAILED: "invalid_auth",
    CONN_UNSUPPORTED_API: "unsupported_api",
    CONN_NO_CONVERSATION: "no_conversation",
    CONN_INVALID_RESPONSE: "invalid_response",
    CONN_UNKNOWN: "unknown",
}


async def _async_test_connection(
    hass: Any, url: str, token: str, verify_tls: bool
) -> tuple[ConnectionState | None, str | None]:
    """Real probe. Returns (state, None) on success or (None, error_key). Never raises."""
    try:
        client = HermesClient(
            async_get_clientsession(hass, verify_ssl=verify_tls),
            url,
            token,
            request_timeout=REQUEST_TIMEOUT,
            inference_timeout=INFERENCE_TIMEOUT,
        )
    except InvalidUrlError:
        return None, "invalid_url"
    except HermesError:
        return None, "invalid_auth"  # empty token
    state = await async_probe(client)
    if state.code == CONN_OK:
        return state, None
    return None, _PROBE_ERRORS.get(state.code, "unknown")


def _connection_schema(
    *, url: str = "", verify_tls: bool = DEFAULT_VERIFY_TLS, token_required: bool = True
) -> vol.Schema:
    token_marker = vol.Required(CONF_TOKEN) if token_required else vol.Optional(CONF_TOKEN)
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=url): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            ),
            token_marker: selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_VERIFY_TLS, default=verify_tls): selector.BooleanSelector(),
        }
    )


class KineticVoiceRouterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the single router entry; it starts in mode off."""

    VERSION = 1
    # 1.1 = 0.3.0 (router_enabled), 1.2 = mode, 1.3 = standalone (Hermes connection in data)
    MINOR_VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        suggested = ""
        if user_input is not None:
            suggested = str(user_input.get(CONF_URL, ""))
            data, error = await self._async_validated(user_input)
            if data is not None:
                return self.async_create_entry(
                    title=NAME, data=data, options={CONF_MODE: DEFAULT_MODE}
                )
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(url=suggested),
            errors=errors,
            description_placeholders={"version": INTEGRATION_VERSION},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Token rejected, or an upgraded 0.4.x entry that has no connection yet."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = await self._async_validated(user_input)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_connection_schema(
                url=str(entry.data.get(CONF_URL, "")),
                verify_tls=bool(entry.data.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS)),
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change URL / TLS check; the stored token is kept if none is entered."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = dict(user_input)
            if not str(candidate.get(CONF_TOKEN, "")).strip():
                candidate[CONF_TOKEN] = entry.data.get(CONF_TOKEN, "")
            data, error = await self._async_validated(candidate)
            if data is not None:
                return self.async_update_reload_and_abort(entry, data_updates=data)
            errors["base"] = error or "unknown"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                url=str(entry.data.get(CONF_URL, "")),
                verify_tls=bool(entry.data.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS)),
                token_required=False,
            ),
            errors=errors,
        )

    async def _async_validated(
        self, user_input: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Run the real connection test; returns (entry data, None) or (None, error key)."""
        url = str(user_input.get(CONF_URL, ""))
        token = str(user_input.get(CONF_TOKEN, ""))
        verify_tls = bool(user_input.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS))
        state, error = await _async_test_connection(self.hass, url, token, verify_tls)
        if state is None:
            return None, error
        return {
            CONF_URL: normalize_url(url),
            CONF_TOKEN: token.strip(),
            CONF_VERIFY_TLS: verify_tls,
        }, None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return KineticVoiceRouterOptionsFlow()


class KineticVoiceRouterOptionsFlow(OptionsFlow):
    """Menu: mode, Hermes connection, test sentence, runtime statistics."""

    def __init__(self) -> None:
        # Last simulation result for the result page: derived labels only, never
        # the test sentence. Lives in this flow object until the dialog closes.
        self._test_result: dict[str, str] | None = None
        # One-shot reset approval (R3.2): set only by the confirmation page, cleared by
        # every other statistics step and consumed by the reset itself. HA already only
        # accepts next_step_id values offered by the current menu; this is defence in depth.
        self._reset_armed = False
        # One-shot approval to wipe the speech memory, same pattern as the counters.
        self._asm_reset_armed = False
        self._asm_edit_key: str | None = None

    def _mode(self) -> str:
        return operating_mode(self.config_entry.options).value

    def _connection_state(self) -> ConnectionState:
        runtime = getattr(self.config_entry, "runtime_data", None)
        return runtime.connection if runtime is not None else ConnectionState()

    def _info(self) -> dict[str, str]:
        lang = language(self.hass)
        return {
            "version": INTEGRATION_VERSION,
            "router_version": ROUTER_VERSION,
            "mode": MODE_LABELS[lang][self._mode()],
            "hermes_status": connection_label(self.hass, self._connection_state().code),
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._reset_armed = False
        self._asm_reset_armed = False
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "connection", "speech_memory", "test", "statistics"],
            description_placeholders=self._info(),
        )

    # --- Hermes-Verbindung -------------------------------------------------------------

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Live status: a real health + capabilities probe each time this page opens.

        Neither the URL nor the token is shown. Changing them is a reconfiguration
        (three-dots menu of the integration), which runs the same test first.
        """
        entry = self.config_entry
        runtime = getattr(entry, "runtime_data", None)
        client = runtime.client if runtime is not None else None
        if client is None and entry.data.get(CONF_URL) and entry.data.get(CONF_TOKEN):
            try:
                client = HermesClient(
                    async_get_clientsession(
                        self.hass, verify_ssl=bool(entry.data.get(CONF_VERIFY_TLS, True))
                    ),
                    entry.data[CONF_URL],
                    entry.data[CONF_TOKEN],
                    request_timeout=REQUEST_TIMEOUT,
                    inference_timeout=INFERENCE_TIMEOUT,
                )
            except HermesError:
                client = None
        state = await async_probe(client) if client is not None else ConnectionState()
        if runtime is not None:
            runtime.connection.code = state.code
            runtime.connection.api_version = state.api_version
            runtime.connection.companion_version = state.companion_version
            runtime.connection.languages = state.languages
        dash = "–"
        return self.async_show_menu(
            step_id="connection",
            menu_options=["connection", "init"],
            description_placeholders={
                "status": connection_label(self.hass, state.code),
                "api_version": state.api_version or dash,
                "companion_version": state.companion_version or dash,
                "tls": (
                    ("an" if language(self.hass) == "de" else "on")
                    if entry.data.get(CONF_VERIFY_TLS, DEFAULT_VERIFY_TLS)
                    else ("aus" if language(self.hass) == "de" else "off")
                ),
            },
        )

    # --- Betriebsart ------------------------------------------------------------------

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._mode()
        errors: dict[str, str] = {}
        if user_input is not None:
            # A submission without the field keeps the stored mode.
            mode = user_input.get(CONF_MODE, current)
            if isinstance(mode, str) and mode in MODES:
                data: dict[str, Any] = {CONF_MODE: mode}
                if CONF_SPEECH_MEMORY in self.config_entry.options:
                    data[CONF_SPEECH_MEMORY] = self.config_entry.options[CONF_SPEECH_MEMORY]
                return self.async_create_entry(title="", data=data)
            errors["base"] = "invalid_mode"
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_MODE, default=current): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(MODES),
                            translation_key="mode",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={"mode": self._info()["mode"]},
        )

    # --- Adaptive Speech Memory (Sprachwörterbuch) ---------------------------------------

    def _speech(self):
        runtime = getattr(self.config_entry, "runtime_data", None)
        return getattr(runtime, "speech", None)

    def _speech_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_SPEECH_MEMORY, DEFAULT_SPEECH_MEMORY) is True

    async def async_step_speech_memory(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Overview: switch state, storage state and every confirmed pair (no sentences)."""
        self._asm_reset_armed = False
        speech = self._speech()
        lang = language(self.hass)
        if speech is None:
            return self.async_show_menu(step_id="speech_memory_unavailable", menu_options=["init"])
        options = ["speech_memory_toggle", "speech_memory_add"]
        if len(speech.memory):
            options += ["speech_memory_edit", "speech_memory_delete"]
        options += ["speech_memory_reset_confirm", "init"]
        return self.async_show_menu(
            step_id="speech_memory",
            menu_options=options,
            description_placeholders={
                "overview": speech_memory_overview(
                    lang,
                    enabled=self._speech_enabled(),
                    mode_active=self._mode() == "active",
                    status=speech.status,
                    entries=speech.memory.entries(),
                    limit=MAX_ENTRIES,
                )
            },
        )

    async def async_step_speech_memory_unavailable(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_init()

    async def async_step_speech_memory_toggle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Opt-in switch. Saving stores it as an option (the entry reloads)."""
        if user_input is not None:
            enabled = user_input.get(CONF_SPEECH_MEMORY) is True
            return self.async_create_entry(
                title="",
                data={CONF_MODE: self._mode(), CONF_SPEECH_MEMORY: enabled},
            )
        return self.async_show_form(
            step_id="speech_memory_toggle",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SPEECH_MEMORY, default=self._speech_enabled()
                    ): selector.BooleanSelector()
                }
            ),
        )

    def _category_selector(self) -> selector.SelectSelector:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[c.value for c in Category],
                translation_key="category",
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    def _entry_selector(self) -> selector.SelectSelector:
        speech = self._speech()
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": e.key, "label": f"{e.heard} → {e.intended}"}
                    for e in speech.memory.entries()
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    async def async_step_speech_memory_add(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        speech = self._speech()
        if speech is None:
            return await self.async_step_speech_memory()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                category = Category(user_input.get(CONF_CATEGORY, Category.NAME.value))
            except ValueError:
                category = Category.NAME
            result = await speech.async_add(
                user_input.get(CONF_HEARD),
                user_input.get(CONF_INTENDED),
                category=category,
                source=Source.MANUAL,
            )
            if isinstance(result, Entry):
                return await self.async_step_speech_memory()
            errors["base"] = f"asm_{result.value}"
        defaults = user_input or {}
        return self.async_show_form(
            step_id="speech_memory_add",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HEARD, default=defaults.get(CONF_HEARD, "")): (
                        selector.TextSelector(selector.TextSelectorConfig())
                    ),
                    vol.Required(CONF_INTENDED, default=defaults.get(CONF_INTENDED, "")): (
                        selector.TextSelector(selector.TextSelectorConfig())
                    ),
                    vol.Required(
                        CONF_CATEGORY, default=defaults.get(CONF_CATEGORY, Category.NAME.value)
                    ): self._category_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_speech_memory_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: pick the pair to edit."""
        speech = self._speech()
        if speech is None or not len(speech.memory):
            return await self.async_step_speech_memory()
        if user_input is not None and speech.memory.get(user_input.get(CONF_ENTRY)) is not None:
            self._asm_edit_key = user_input[CONF_ENTRY]
            return await self.async_step_speech_memory_edit_entry()
        return self.async_show_form(
            step_id="speech_memory_edit",
            data_schema=vol.Schema({vol.Required(CONF_ENTRY): self._entry_selector()}),
        )

    async def async_step_speech_memory_edit_entry(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: new meaning and category; the misheard phrase itself stays the key."""
        speech = self._speech()
        entry = speech.memory.get(self._asm_edit_key) if speech is not None else None
        if entry is None:
            return await self.async_step_speech_memory()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                category = Category(user_input.get(CONF_CATEGORY, entry.category.value))
            except ValueError:
                category = entry.category
            result = await speech.async_update(
                entry.heard, user_input.get(CONF_INTENDED), category=category
            )
            if isinstance(result, Entry):
                self._asm_edit_key = None
                return await self.async_step_speech_memory()
            errors["base"] = f"asm_{result.value}"
        return self.async_show_form(
            step_id="speech_memory_edit_entry",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INTENDED, default=entry.intended): selector.TextSelector(
                        selector.TextSelectorConfig()
                    ),
                    vol.Required(
                        CONF_CATEGORY, default=entry.category.value
                    ): self._category_selector(),
                }
            ),
            errors=errors,
            description_placeholders={"heard": entry.heard},
        )

    async def async_step_speech_memory_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        speech = self._speech()
        if speech is None or not len(speech.memory):
            return await self.async_step_speech_memory()
        errors: dict[str, str] = {}
        if user_input is not None:
            if await speech.async_delete(user_input.get(CONF_ENTRY)):
                return await self.async_step_speech_memory()
            errors["base"] = "asm_read_only" if not speech.writable else "asm_unknown_entry"
        return self.async_show_form(
            step_id="speech_memory_delete",
            data_schema=vol.Schema({vol.Required(CONF_ENTRY): self._entry_selector()}),
            errors=errors,
        )

    async def async_step_speech_memory_reset_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explicit confirmation page; the only way to empty (or repair) the lexicon."""
        self._asm_reset_armed = True
        return self.async_show_menu(
            step_id="speech_memory_reset_confirm",
            menu_options=["speech_memory_reset_execute", "speech_memory"],
        )

    async def async_step_speech_memory_reset_execute(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        speech = self._speech()
        if self._asm_reset_armed and speech is not None:
            self._asm_reset_armed = False
            await speech.async_reset()
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is not None:
                runtime.bridge.store.clear_proposals()
        return await self.async_step_speech_memory()

    # --- Testanfrage ------------------------------------------------------------------

    async def async_step_test(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Input form. Only the router classification is simulated.

        No Hermes call, no device or service action, no session state, no
        statistics, no logging; the sentence is neither saved as an option nor
        echoed back. Whether Home Assistant would handle it locally is NOT tested.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            sentence = user_input.get(CONF_TEST_SENTENCE)
            if isinstance(sentence, str) and sentence.strip():
                lang = language(self.hass)
                decision = simulate(sentence, getattr(self.hass.config, "language", None))
                lane = decision.lane.value
                self._test_result = {
                    "route": f"{ROUTE_LABELS[lang][lane]} (`{lane}`)",
                    "rule": decision.rule_id,
                    "reason": REASONS[lang].get(decision.reason_code, decision.reason_code.value),
                    "answer": decision.response
                    if decision.response is not None
                    else FORWARD_TO_HERMES[lang],
                }
                return await self.async_step_test_result()
            errors["base"] = "empty_test_sentence"
        return self.async_show_form(
            step_id="test",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TEST_SENTENCE): selector.TextSelector(
                        selector.TextSelectorConfig()
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_test_result(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Result page: four separate lines, then new request or back to the menu."""
        if self._test_result is None:
            return await self.async_step_test()
        return self.async_show_menu(
            step_id="test_result",
            menu_options=["test", "init"],
            description_placeholders=self._test_result,
        )

    # --- Laufzeitstatistik ------------------------------------------------------------

    async def async_step_statistics(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Summary first; opening or navigating never resets anything."""
        self._reset_armed = False
        snap = runtime_stats(self.hass).snapshot()
        return self.async_show_menu(
            step_id="statistics",
            menu_options=["statistics_details", "reset_confirm", "init"],
            description_placeholders={
                "summary": statistics_summary(language(self.hass), snap, self._mode())
            },
        )

    async def async_step_statistics_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._reset_armed = False
        snap = runtime_stats(self.hass).snapshot()
        return self.async_show_menu(
            step_id="statistics_details",
            menu_options=["statistics", "init"],
            description_placeholders={
                "details": statistics_details(language(self.hass), snap),
                "router_version": ROUTER_VERSION,
            },
        )

    async def async_step_reset_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explicit confirmation page with a reset entry and a cancel entry."""
        self._reset_armed = True
        return self.async_show_menu(
            step_id="reset_confirm", menu_options=["reset_execute", "statistics"]
        )

    async def async_step_reset_execute(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Resets only with a fresh approval from the confirmation page, then shows the
        summary. Without approval (direct call, after cancel, second time) nothing resets."""
        if self._reset_armed:
            self._reset_armed = False
            runtime_stats(self.hass).reset()
        return await self.async_step_statistics()
