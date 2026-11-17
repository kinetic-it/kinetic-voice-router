"""Autorisierung der einzigen ausfuehrbaren Aktion des Routers.

Der Router-Kern bleibt ausfuehrungsfrei: hier steht ausschliesslich die
Allowlist-Pruefung, die ein Ziel zulaesst oder mit `PermissionError` ablehnt.
Kein Home-Assistant-Import, keine Ausfuehrung.
"""

from __future__ import annotations

from .alarm import AUTHORIZED_TARGETS
from .model import AuthorizedAction


def ensure_authorized_target(action: AuthorizedAction) -> tuple[str, str]:
    """Fail-closed: nur Ziele aus ``AUTHORIZED_TARGETS`` kommen durch.

    Jede andere Kombination - fremde Domain, fremder Dienst, leere Werte -
    endet in `PermissionError`, bevor irgendein Dienstaufruf entstehen kann.
    """
    if not isinstance(action, AuthorizedAction):
        raise PermissionError("unauthorized target")
    if (action.domain, action.service) not in AUTHORIZED_TARGETS:
        raise PermissionError("unauthorized target")
    return action.domain, action.service
