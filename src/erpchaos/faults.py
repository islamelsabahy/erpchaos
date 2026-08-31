from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from erpchaos.events import BusinessEvent


class FaultType(StrEnum):
    duplicate_event = "duplicate_event"
    drop_event = "drop_event"
    delay_event = "delay_event"
    reorder_event = "reorder_event"
    partial_failure = "partial_failure"


class FaultSpec(BaseModel):
    """A deterministic mutation applied to an ordered business event stream."""

    type: FaultType
    target_event_id: str
    repeat: int = Field(default=1, ge=1, le=20)
    positions: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_parameters(self) -> FaultSpec:
        if self.type != FaultType.duplicate_event and self.repeat != 1:
            raise ValueError("repeat is only valid for duplicate_event")
        movable_faults = {FaultType.delay_event, FaultType.reorder_event}
        if self.type not in movable_faults and self.positions != 1:
            raise ValueError("positions is only valid for delay_event or reorder_event")
        return self


class ChaosScenario(BaseModel):
    name: str
    description: str | None = None
    faults: list[FaultSpec] = Field(min_length=1)


def _find_event_index(events: list[BusinessEvent], event_id: str) -> int:
    for index, event in enumerate(events):
        if event.event_id == event_id:
            return index
    raise ValueError(f"Target event not found: {event_id}")


def apply_fault(events: list[BusinessEvent], fault: FaultSpec) -> list[BusinessEvent]:
    """Return a new event list with one deterministic fault applied."""

    mutated = [event.model_copy(deep=True) for event in events]
    index = _find_event_index(mutated, fault.target_event_id)

    if fault.type == FaultType.duplicate_event:
        source = mutated[index]
        duplicates = [
            source.model_copy(update={"event_id": f"{source.event_id}#dup{number}"}, deep=True)
            for number in range(1, fault.repeat + 1)
        ]
        mutated[index + 1 : index + 1] = duplicates
        return mutated

    if fault.type == FaultType.drop_event:
        del mutated[index]
        return mutated

    if fault.type == FaultType.delay_event:
        event = mutated.pop(index)
        destination = min(index + fault.positions, len(mutated))
        mutated.insert(destination, event)
        return mutated

    if fault.type == FaultType.reorder_event:
        destination = max(0, index - fault.positions)
        event = mutated.pop(index)
        mutated.insert(destination, event)
        return mutated

    if fault.type == FaultType.partial_failure:
        return mutated[: index + 1]

    raise ValueError(f"Unsupported fault type: {fault.type}")
