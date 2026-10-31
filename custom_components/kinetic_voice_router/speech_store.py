"""Local persistence of the Adaptive Speech Memory with Home Assistant's `Store`.

- One file `.storage/kinetic_voice_router.speech_memory`, written atomically and
  marked private (Home Assistant helpers, no own file handling).
- Versioned payload (`STORE_VERSION`); migrations go through `_async_migrate_func`.
- Only confirmed word pairs with category, source and a date are stored. No sentences,
  conversation IDs, audio, tokens or person profiles.
- A file that cannot be read or validated is never overwritten automatically: the
  lexicon becomes read-only and the options show the problem until the user resets it.
  (Home Assistant itself moves syntactically broken JSON aside as `*.corrupt.<time>`
  and raises a repair issue; that original file is kept.)
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .voice_router.speech_memory import (
    Category,
    Entry,
    LoadError,
    Rejection,
    Source,
    SpeechMemory,
    load_entries,
)

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
STORE_MINOR_VERSION = 1
STORE_KEY = f"{DOMAIN}.speech_memory"

STATUS_OK = "ok"
STATUS_INVALID = "invalid"  # readable JSON, but not a valid lexicon
STATUS_UNREADABLE = "unreadable"  # newer version or read error


class _LexiconStore(Store[dict[str, Any]]):
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        # Version 1 is the first format. Future formats add their steps here.
        raise NotImplementedError


class SpeechMemoryStore:
    """The lexicon of this installation plus its storage status."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = _LexiconStore(
            hass,
            STORE_VERSION,
            STORE_KEY,
            private=True,
            atomic_writes=True,
            minor_version=STORE_MINOR_VERSION,
        )
        self.memory = SpeechMemory()
        self.status = STATUS_OK

    @property
    def writable(self) -> bool:
        return self.status == STATUS_OK

    async def async_load(self) -> None:
        try:
            data = await self._store.async_load()
        except (HomeAssistantError, OSError, ValueError, TypeError) as err:
            _LOGGER.error(
                "Speech memory could not be read (%s); it stays unchanged", type(err).__name__
            )
            self.status = STATUS_UNREADABLE
            self.memory = SpeechMemory()
            return
        try:
            entries = load_entries(data)
        except LoadError as err:
            _LOGGER.error("Speech memory is invalid (%s); it stays unchanged", err)
            self.status = STATUS_INVALID
            self.memory = SpeechMemory()
            return
        self.status = STATUS_OK
        self.memory = SpeechMemory(entries)

    async def _async_save(self) -> None:
        await self._store.async_save(self.memory.export_data())

    async def async_add(
        self,
        heard: object,
        intended: object,
        *,
        category: Category,
        source: Source,
        replace_existing: bool = False,
    ) -> Entry | Rejection:
        if not self.writable:
            return Rejection.READ_ONLY
        result = self.memory.add(
            heard,
            intended,
            category=category,
            source=source,
            today=_today(),
            replace_existing=replace_existing,
        )
        if isinstance(result, Entry):
            await self._async_save()
        return result

    async def async_update(
        self, heard: object, intended: object, *, category: Category
    ) -> Entry | Rejection:
        if not self.writable:
            return Rejection.READ_ONLY
        result = self.memory.update(heard, intended, category=category, today=_today())
        if isinstance(result, Entry):
            await self._async_save()
        return result

    async def async_delete(self, heard: object) -> bool:
        if not self.writable or not self.memory.delete(heard):
            return False
        await self._async_save()
        return True

    async def async_reset(self) -> None:
        """Explicit user action only: empty lexicon, and the store becomes usable again."""
        self.memory = SpeechMemory()
        self.status = STATUS_OK
        await self._async_save()

    async def async_remove(self) -> None:
        """Integration deleted by the user: remove the stored lexicon too."""
        await self._store.async_remove()


def _today() -> str:
    return datetime.date.today().isoformat()
