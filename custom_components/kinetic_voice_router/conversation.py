"""Conversation agent of the Kinetic Voice Router.

Home Assistant calls this agent only for sentences its own local intents did not
handle (`prefer_local_intents`, set in the Assist pipeline by the user). The agent:

- mode OFF:     forwards the turn to the Hermes Companion, unchanged;
- mode OBSERVE: additionally counts the router decision in memory, then forwards the
                turn exactly like OFF (the answer is never altered);
- mode ACTIVE:  lets the router policy decide (short honest answers for device or
                status requests, checked Hermes answers for conversation).

Adaptive Speech Memory (optional, default off, mode ACTIVE only): confirmed word
pairs are applied to harmless conversation before it reaches Hermes; a correction
such as "Nein, ich meinte Mulan" continues the original request and, if the misheard
word is reliably known, asks once whether to remember the pair. Only an explicit
"Ja" in the same conversation stores it.

It never calls Home Assistant services, never switches devices, never changes
exposures or the Assist pipeline, and never stores or logs the spoken text.
"""

from __future__ import annotations

import logging
import re
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
from .voice_router import responses
from .voice_router.classify import is_device_term, normalize
from .voice_router.model import Lane, ReasonCode
from .voice_router.speech_memory import (
    AUTO_APPLY,
    Entry,
    is_confirmation,
    is_decline,
    parse_correction,
    suggested_category,
)
from .voice_router.speech_memory import (
    Source as MemorySource,
)

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
        speech = runtime.speech if bridge.enabled and runtime.speech_enabled else None

        # 1. Answer to an open learning proposal ("Soll ich mir merken ...?").
        if speech is not None:
            proposal = bridge.store.pop_proposal(session_id)
            if proposal is not None and _previous_assistant_text(chat_log, user_input.agent_id):
                reply_text = await self._answer_proposal(proposal, user_input.text)
                if reply_text is not None:
                    return self._answer(user_input, chat_log, reply_text, arm_followup=False)

        # Consume a bounded question token only if HA really supplied the prior
        # assistant turn in the same ChatLog. The token stores no spoken text.
        chat_followup = False
        if bridge.enabled:
            chat_followup = bridge.store.pop_chat_followup(session_id) and _previous_chat_question(
                chat_log, user_input.agent_id
            )

        # 2. Correction of the previous request, 3. learned pairs (both Active + opt-in).
        route_text = user_input.text
        correction = None
        if speech is not None and not chat_followup:
            correction = parse_correction(user_input.text, _previous_user_text(chat_log))
            if correction is not None:
                # Continue the ORIGINAL request with the corrected word; the user does
                # not have to repeat the sentence. It is routed and checked like any turn.
                previous = _previous_user_text(chat_log) or ""
                route_text = _replace_phrase(previous, correction.heard, correction.intended)
            else:
                route_text = speech.memory.apply(user_input.text) or user_input.text
            if route_text != user_input.text:
                messages = _with_last_user_text(messages, route_text)

        async def call_hermes() -> str | None:
            return await self._ask_hermes(messages, session_id, user_input.language)

        if bridge.enabled:
            reply = await bridge.async_handle(
                text=route_text,
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
                text = reply.text
                if reply.decision.reason_code is ReasonCode.CHAT_FOLLOWUP_UNCLEAR:
                    text = _repeat_question(chat_log, user_input.agent_id) or text
                if (
                    correction is not None
                    and speech is not None
                    and reply.hermes_called
                    and reply.decision.lane is Lane.CHAT
                ):
                    question = self._proposal_question(correction.heard, correction.intended)
                    if question is not None and bridge.store.set_proposal(
                        session_id, correction.heard, correction.intended
                    ):
                        return self._answer(
                            user_input, chat_log, f"{text} {question}", arm_followup=False
                        )
                return self._answer(user_input, chat_log, text)

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

    def _proposal_question(self, heard: str, intended: str) -> str | None:
        """The one learning question, or None if nothing should be asked."""
        speech = self._runtime.speech
        if speech is None or not speech.writable:
            return None
        existing = speech.memory.get(heard)
        if existing is None:
            return responses.ASM_PROPOSE.format(heard=heard, intended=intended)
        if existing.intended.casefold() == intended.casefold():
            return None  # already known: nothing to ask
        return responses.ASM_PROPOSE_REPLACE.format(
            heard=existing.heard, old=existing.intended, intended=intended
        )

    async def _answer_proposal(self, proposal: tuple[str, str], text: str) -> str | None:
        """Explicit yes stores the pair, explicit no drops it, anything else: normal turn."""
        speech = self._runtime.speech
        heard, intended = proposal
        if is_decline(text):
            return responses.ASM_NOT_LEARNED
        if not is_confirmation(text) or speech is None:
            return None
        result = await speech.async_add(
            heard,
            intended,
            category=suggested_category(heard),
            source=MemorySource.DIALOGUE,
            replace_existing=True,  # the question already named the old pair
        )
        if not isinstance(result, Entry):
            return responses.ASM_CANNOT_LEARN
        template = (
            responses.ASM_LEARNED
            if result.category in AUTO_APPLY
            else responses.ASM_LEARNED_NO_AUTO
        )
        return template.format(heard=result.heard, intended=result.intended)

    def _answer(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        text: str,
        *,
        arm_followup: bool = True,
    ) -> conversation.ConversationResult:
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=text)
        )
        if self._runtime.bridge.enabled and arm_followup:
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


def _previous_assistant_text(chat_log: Any, agent_id: str) -> str | None:
    """Text of this agent's turn right before the current user turn, if any."""
    content = getattr(chat_log, "content", ())
    if len(content) < 2:
        return None
    previous = content[-2]
    if getattr(previous, "role", None) != "assistant" or getattr(previous, "agent_id", None) != (
        agent_id
    ):
        return None
    text = getattr(previous, "content", None)
    return text if isinstance(text, str) else None


def _previous_user_text(chat_log: Any) -> str | None:
    """The user's previous turn in this conversation (HA keeps it in the ChatLog)."""
    content = list(getattr(chat_log, "content", ()))[:-1]  # without the current turn
    for item in reversed(content):
        if getattr(item, "role", None) == "user":
            text = getattr(item, "content", None)
            return text if isinstance(text, str) else None
    return None


def _repeat_question(chat_log: Any, agent_id: str) -> str | None:
    """'Ich habe dich nicht richtig verstanden. Kaffee oder Tee?' - the short question
    is taken from HA's ChatLog of this conversation, nothing is stored by the router."""
    previous = _previous_assistant_text(chat_log, agent_id)
    if previous is None:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", previous.strip())
    question = sentences[-1] if sentences else ""
    if not question.endswith("?") or len(question) > 120:
        return None
    if question.startswith(responses.CHAT_FOLLOWUP_UNCLEAR_PREFIX):
        return previous  # already the repeat: say it again unchanged
    return f"{responses.CHAT_FOLLOWUP_UNCLEAR_PREFIX} {question}"


def _replace_phrase(text: str, heard: str, intended: str) -> str:
    pattern = re.compile(r"(?<![^\W\d_])" + re.escape(heard) + r"(?![^\W\d_])", re.IGNORECASE)
    return pattern.sub(intended, text)


def _with_last_user_text(messages: list[dict[str, str]], text: str) -> list[dict[str, str]]:
    """Hermes request with the corrected current user turn; HA's ChatLog stays as heard."""
    updated = [dict(message) for message in messages]
    for message in reversed(updated):
        if message["role"] == "user":
            message["content"] = text
            break
    return updated


def _messages(chat_log: Any) -> list[dict[str, str]]:
    """Bounded history: HA already appended the current user turn."""
    messages: list[dict[str, str]] = []
    for item in chat_log.content[-20:]:
        content = getattr(item, "content", None)
        role = getattr(item, "role", None)
        if role in {"system", "user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    return messages
