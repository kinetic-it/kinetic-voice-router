"""Runtime objects of a loaded config entry."""

from __future__ import annotations

from dataclasses import dataclass

from .hermes_client import HermesClient
from .speech_store import SpeechMemoryStore
from .status import ConnectionState
from .voice_router import RouterBridge


@dataclass
class RouterRuntime:
    """Router policy, Hermes client and the last real connection observation."""

    bridge: RouterBridge
    client: HermesClient
    connection: ConnectionState
    speech: SpeechMemoryStore | None = None
    speech_enabled: bool = False  # option "speech_memory"; learning is opt-in
