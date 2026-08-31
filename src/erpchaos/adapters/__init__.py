from __future__ import annotations

from typing import Protocol

from erpchaos.events import EventStream


class EventStreamAdapter(Protocol):
    """Boundary implemented by ERP-specific read adapters."""

    def translate(self) -> list[EventStream]:
        """Translate source activity into vendor-neutral event streams."""
        ...
