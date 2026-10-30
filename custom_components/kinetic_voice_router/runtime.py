"""Runtime objects of a loaded config entry."""

from __future__ import annotations

from dataclasses import dataclass

from .hermes_client import HermesClient
from .status import ConnectionState
from .voice_router import RouterBridge


@dataclass
class RouterRuntime:
    """Router policy, Hermes client and the last real connection observation."""

    bridge: RouterBridge
    client: HermesClient
    connection: ConnectionState
