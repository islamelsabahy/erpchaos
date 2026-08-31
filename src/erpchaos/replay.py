from __future__ import annotations

from pydantic import BaseModel

from erpchaos.events import BusinessEvent, EventStream
from erpchaos.faults import ChaosScenario, apply_fault


class ReplayResult(BaseModel):
    transaction_id: str
    scenario: str
    original_events: list[BusinessEvent]
    mutated_events: list[BusinessEvent]

    @property
    def changed(self) -> bool:
        return self.original_events != self.mutated_events


def replay(stream: EventStream, scenario: ChaosScenario) -> ReplayResult:
    """Apply a chaos scenario to a transaction event stream in a deterministic order."""

    mutated = [event.model_copy(deep=True) for event in stream.events]
    for fault in scenario.faults:
        mutated = apply_fault(mutated, fault)

    return ReplayResult(
        transaction_id=stream.transaction_id,
        scenario=scenario.name,
        original_events=[event.model_copy(deep=True) for event in stream.events],
        mutated_events=mutated,
    )
