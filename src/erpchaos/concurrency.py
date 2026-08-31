from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from erpchaos.engine import InvariantResult, reliability_score
from erpchaos.events import BusinessEvent, EventStream


class ConcurrencyScenario(BaseModel):
    """Deterministic interleaving of transactions competing for one resource."""

    name: str
    description: str | None = None
    resource_key: str
    success_event_type: str
    max_successes: int = Field(default=1, ge=1)
    streams: list[EventStream] = Field(min_length=2)
    schedule: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_schedule(self) -> ConcurrencyScenario:
        transaction_ids = [stream.transaction_id for stream in self.streams]
        if len(transaction_ids) != len(set(transaction_ids)):
            raise ValueError("transaction_id values must be unique across competing streams")

        expected = {
            stream.transaction_id: len(stream.events)
            for stream in self.streams
        }
        actual = dict(Counter(self.schedule))

        unknown = set(actual) - set(expected)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"schedule references unknown transaction(s): {names}")

        if actual != expected:
            raise ValueError(
                "schedule must consume every event exactly once; "
                f"expected {expected}, got {actual}"
            )
        return self


@dataclass(frozen=True)
class InterleavedEvent:
    position: int
    transaction_id: str
    event: BusinessEvent


@dataclass(frozen=True)
class ConcurrencyResult:
    scenario: str
    resource_key: str
    timeline: list[InterleavedEvent]
    successful_transactions: list[str]
    max_successes: int
    invariant_result: InvariantResult
    score: int

    @property
    def passed(self) -> bool:
        return self.invariant_result.passed



def _interleave(scenario: ConcurrencyScenario) -> list[InterleavedEvent]:
    events_by_transaction = {
        stream.transaction_id: stream.events
        for stream in scenario.streams
    }
    offsets = {transaction_id: 0 for transaction_id in events_by_transaction}
    timeline: list[InterleavedEvent] = []

    for position, transaction_id in enumerate(scenario.schedule, start=1):
        offset = offsets[transaction_id]
        event = events_by_transaction[transaction_id][offset]
        offsets[transaction_id] = offset + 1
        timeline.append(
            InterleavedEvent(
                position=position,
                transaction_id=transaction_id,
                event=event.model_copy(deep=True),
            )
        )

    return timeline



def run_concurrency(scenario: ConcurrencyScenario) -> ConcurrencyResult:
    """Interleave competing streams and evaluate shared-resource exclusivity."""

    timeline = _interleave(scenario)
    successful_transactions: list[str] = []
    seen: set[str] = set()

    for item in timeline:
        if (
            item.event.event_type == scenario.success_event_type
            and item.transaction_id not in seen
        ):
            successful_transactions.append(item.transaction_id)
            seen.add(item.transaction_id)

    success_count = len(successful_transactions)
    invariant_result = InvariantResult(
        name="shared-resource-exclusivity",
        passed=success_count <= scenario.max_successes,
        actual=success_count,
        expected=f"<= {scenario.max_successes}",
        severity="critical",
    )

    return ConcurrencyResult(
        scenario=scenario.name,
        resource_key=scenario.resource_key,
        timeline=timeline,
        successful_transactions=successful_transactions,
        max_successes=scenario.max_successes,
        invariant_result=invariant_result,
        score=reliability_score([invariant_result]),
    )
