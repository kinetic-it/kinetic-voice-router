"""Conversation agent of the Kinetic Voice Router.

Home Assistant calls this agent only for sentences its own local intents did not
handle (`prefer_local_intents`, set in the Assist pipeline by the user). The agent:

- mode OFF:     forwards the turn to the Hermes Companion, unchanged;
- mode OBSERVE: additionally counts the router decision in memory, then forwards the
                turn exactly like OFF (the answer is never altered);
- mode ACTIVE:  lets the router policy decide (short honest answers for device or
                status requests, checked Hermes answers for conversation).

It never calls Home Assistant services, never switches devices, never changes
exposures or the Assist pipeline, and never stores or logs the spoken text.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, override

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONN_OK, NAME
from .hermes_client import HermesError
from .runtime import RouterRuntime
from .status import code_for_error
from .voice_router.classify import is_device_term, normalize

_LOGGER = logging.getLogger(__name__)

HERMES_FAILED = "Hermes Agent could not process the request."
# Errors the router treats as an answer-level failure of the Hermes call.
_HERMES_ERRORS = (HermesError, TypeError, ValueError)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry[RouterRuntime],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register the single conversation entity of this entry."""
    async_add_entities([KineticVoiceRouterConversationEntity(config_entry)])


class KineticVoiceRouterConversationEntity(conversation.ConversationEntity):
    """Native Home Assistant conversation entity: router policy in front of Hermes."""

    _attr_has_entity_name = False

    def __init__(self, entry: ConfigEntry[RouterRuntime]) -> None:
        self._entry = entry
        self._attr_name = NAME
        self._attr_unique_id = f"{entry.entry_id}-conversation"

    @property
    def _runtime(self) -> RouterRuntime:
        return self._entry.runtime_data

    @property
    @override
    def supported_languages(self) -> list[str] | Literal["*"]:
        languages = self._runtime.connection.languages
        # Home Assistant requires the wildcard as the literal string "*", not ["*"].
        # The Hermes Companion advertises wildcard support as a JSON language list.
        if not languages or MATCH_ALL in languages:
            return MATCH_ALL
        return list(languages)

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self._entry, self)

    @override
    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self._entry)
        await super().async_will_remove_from_hass()

    @override
    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        runtime = self._runtime
        bridge = runtime.bridge
        messages = _messages(chat_log)

        if bridge.observing:
            # Count only; this turn continues unchanged below.
            try:
                bridge.observe(text=user_input.text, language=user_input.language)
            except Exception as err:  # noqa: BLE001 - observation must never affect a turn
                _LOGGER.debug("Observation failed (%s)", type(err).__name__)

        # HA's chat session ID is always set; user_input.conversation_id may be None.
        session_id = getattr(chat_log, "conversation_id", None) or user_input.conversation_id
        # Consume a bounded question token only if HA really supplied the prior
        # assistant turn in the same ChatLog. The token stores no spoken text.
        chat_followup = False
        if bridge.enabled:
            chat_followup = bridge.store.pop_chat_followup(session_id) and _previous_chat_question(
                chat_log, user_input.agent_id
            )

        async def call_hermes() -> str | None:
            return await self._ask_hermes(messages, session_id, user_input.language)

        if bridge.enabled:
            reply = await bridge.async_handle(
                text=user_input.text,
                language=user_input.language,
                conversation_id=session_id,
                call_hermes=call_hermes,
                hermes_errors=_HERMES_ERRORS,
                chat_followup=chat_followup,
            )
            if reply is not None:
                _LOGGER.debug("Router decision: %s", reply.decision.trace())
                if reply.is_error:
                    response = intent.IntentResponse(language=user_input.language)
                    response.async_set_error(
                        intent.IntentResponseErrorCode.FAILED_TO_HANDLE, reply.text
                    )
                    # Return the session ID so a follow-up "Warum?" is bound to this error.
                    return conversation.ConversationResult(
                        response=response, conversation_id=session_id
                    )
                return self._answer(user_input, chat_log, reply.text)

        # OFF, OBSERVE (and ACTIVE when the router abstains): plain Hermes conversation.
        try:
            text = await call_hermes()
            if text is None:
                raise ValueError("empty inference response")
        except _HERMES_ERRORS as err:
            _LOGGER.error("Hermes conversation request failed (%s)", type(err).__name__)
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_error(intent.IntentResponseErrorCode.FAILED_TO_HANDLE, HERMES_FAILED)
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )
        return self._answer(user_input, chat_log, text)

    async def _ask_hermes(
        self, messages: list[dict[str, str]], session_id: str | None, language: str | None
    ) -> str | None:
        """One Hermes call. Records the real outcome as connection status."""
        runtime = self._runtime
        try:
            text = await runtime.client.async_inference(
                messages, conversation_id=session_id, language=language
            )
        except HermesError as err:
            runtime.connection.code = code_for_error(err)
            raise
        runtime.connection.code = CONN_OK
        return text

    def _answer(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        text: str,
    ) -> conversation.ConversationResult:
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=text)
        )
        if self._runtime.bridge.enabled:
            session_id = getattr(chat_log, "conversation_id", None) or user_input.conversation_id
            store = self._runtime.bridge.store
            if _safe_chat_question(text):
                store.set_chat_followup(session_id)
            else:
                store.clear_chat_followup(session_id)
        return conversation.async_get_result_from_chat_log(user_input, chat_log)


def _safe_chat_question(text: str) -> bool:
    """Only spoken questions without known HA device words arm a chat follow-up."""
    return text.strip().endswith(("?", "？", ";")) and not any(
        is_device_term(token) for token in normalize(text).split()
    )


def _previous_chat_question(chat_log: Any, agent_id: str) -> bool:
    """Require a genuine previous assistant turn, not a newly supplied command."""
    content = getattr(chat_log, "content", ())
    if len(content) < 2:
        return False
    previous = content[-2]  # HA appended current user input as the last content.
    return (
        getattr(previous, "role", None) == "assistant"
        and getattr(previous, "agent_id", None) == agent_id
        and isinstance(getattr(previous, "content", None), str)
        and _safe_chat_question(previous.content)
    )


def _messages(chat_log: Any) -> list[dict[str, str]]:
    """Bounded history: HA already appended the current user turn."""
    messages: list[dict[str, str]] = []
    for item in chat_log.content[-20:]:
        content = getattr(item, "content", None)
        role = getattr(item, "role", None)
        if role in {"system", "user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    return messages
