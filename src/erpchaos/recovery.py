from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from erpchaos.effects import EffectMap
from erpchaos.engine import InvariantResult, reliability_score, verify_contract
from erpchaos.events import BusinessEvent, EventStream
from erpchaos.experiment import ExperimentResult, run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.models import BusinessReliabilityContract
from erpchaos.projection import project_business_state


class RecoveryContract(BusinessReliabilityContract):
    """Business invariants that must become true after deterministic compensation."""

    contract_type: Literal["recovery"] = "recovery"


class RecoveryScenario(BaseModel):
    """Ordered compensating events applied after a known chaos-induced business failure."""

    name: str = Field(min_length=1)
    events: list[BusinessEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> RecoveryScenario:
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("recovery event IDs must be unique")
        return self


class RecoveryStatus(StrEnum):
    recovered = "RECOVERED"
    partially_recovered = "PARTIALLY_RECOVERED"
    unrecovered = "UNRECOVERED"


@dataclass(frozen=True)
class RecoveryCheckpoint:
    step: int
    event_id: str
    event_type: str
    score: int
    passed: bool


@dataclass(frozen=True)
class RecoveryResult:
    chaos: ExperimentResult
    recovery_scenario: str
    projected_state: dict[str, Any]
    invariant_results: list[InvariantResult]
    score: int
    status: RecoveryStatus
    ttbc_steps: int | None
    regressed_after_recovery: bool
    checkpoints: list[RecoveryCheckpoint]

    @property
    def passed(self) -> bool:
        return self.status is RecoveryStatus.recovered


def run_recovery_experiment(
    business_contract: BusinessReliabilityContract,
    chaos_scenario: ChaosScenario,
    stream: EventStream,
    recovery_contract: RecoveryContract,
    recovery_scenario: RecoveryScenario,
    effect_map: EffectMap | None = None,
    lineage_policy: EffectLineagePolicy | None = None,
) -> RecoveryResult:
    """Apply chaos and deterministic recovery events until recovery is exhausted."""

    chaos_result = run_experiment(
        business_contract,
        chaos_scenario,
        stream,
        effect_map,
        lineage_policy,
    )
    if chaos_result.passed:
        raise ValueError("recovery experiments require chaos to fail the business contract first")

    timeline = list(chaos_result.replay.mutated_events)
    existing_ids = {event.event_id for event in timeline}
    duplicate_ids = [
        event.event_id for event in recovery_scenario.events if event.event_id in existing_ids
    ]
    if duplicate_ids:
        names = ", ".join(sorted(set(duplicate_ids)))
        raise ValueError(f"recovery event IDs must not reuse post-chaos event IDs: {names}")

    checkpoints: list[RecoveryCheckpoint] = []
    ttbc_steps: int | None = None
    final_state = project_business_state(timeline, effect_map, lineage_policy)
    final_results = verify_contract(recovery_contract, final_state)
    final_score = reliability_score(final_results)

    if all(result.passed for result in final_results):
        ttbc_steps = 0

    for step, event in enumerate(recovery_scenario.events, start=1):
        timeline.append(event)
        final_state = project_business_state(timeline, effect_map, lineage_policy)
        final_results = verify_contract(recovery_contract, final_state)
        final_score = reliability_score(final_results)
        passed = all(result.passed for result in final_results)
        checkpoints.append(
            RecoveryCheckpoint(
                step=step,
                event_id=event.event_id,
                event_type=event.event_type,
                score=final_score,
                passed=passed,
            )
        )
        if passed and ttbc_steps is None:
            ttbc_steps = step

    status = _classify_recovery(final_results)
    regressed_after_recovery = ttbc_steps is not None and status is not RecoveryStatus.recovered
    return RecoveryResult(
        chaos=chaos_result,
        recovery_scenario=recovery_scenario.name,
        projected_state=final_state,
        invariant_results=final_results,
        score=final_score,
        status=status,
        ttbc_steps=ttbc_steps,
        regressed_after_recovery=regressed_after_recovery,
        checkpoints=checkpoints,
    )


def _classify_recovery(results: list[InvariantResult]) -> RecoveryStatus:
    passed_count = sum(result.passed for result in results)
    if passed_count == len(results):
        return RecoveryStatus.recovered
    if passed_count > 0:
        return RecoveryStatus.partially_recovered
    return RecoveryStatus.unrecovered
