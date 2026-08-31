from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BusinessEvent(BaseModel):
    """A vendor-neutral business event used by the deterministic replay engine."""

    event_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class EventStream(BaseModel):
    """An ordered transaction event stream."""

    transaction_id: str
    events: list[BusinessEvent] = Field(min_length=1)
