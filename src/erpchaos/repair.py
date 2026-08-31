from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import permutations
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erpchaos.effects import EffectMap
from erpchaos.engine import InvariantResult, reliability_score, verify_contract
from erpchaos.events import BusinessEvent, EventStream
from erpchaos.experiment import ExperimentResult, run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.projection import project_business_state
from erpchaos.recovery import RecoveryContract


class RepairCandidate(BaseModel):
    """One explicitly allowed compensating business event template."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class RepairCatalog(BaseModel):
    """Bounded deterministic search space for repair synthesis."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.repair-catalog.v1"] = Field(alias="schema")
    name: str = Field(min_length=1)
    max_plan_length: int = Field(ge=1, le=8)
    candidates: list[RepairCandidate] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> RepairCatalog:
        names = [candidate.name for candidate in self.candidates]
        if len(names) != len(set(names)):
            raise ValueError("repair candidate names must be unique")
        return self


class RepairStatus(StrEnum):
    found = "REPAIR_FOUND"
    not_found = "NO_REPAIR_FOUND"


@dataclass(frozen=True)
class RepairPlanResult:
    chaos: ExperimentResult
    catalog: str
    status: RepairStatus
    searched_plan_count: int
    selected_candidate_names: list[str]
    generated_events: list[BusinessEvent]
    projected_state: dict[str, Any]
    invariant_results: list[InvariantResult]
    score: int

    @property
    def passed(self) -> bool:
        return self.status is RepairStatus.found

    @property
    def plan_length(self) -> int | None:
        if not self.passed:
            return None
        return len(self.generated_events)


def synthesize_repair_plan(
    business_contract: RecoveryContract | Any,
    chaos_scenario: ChaosScenario,
    stream: EventStream,
    recovery_contract: RecoveryContract,
    catalog: RepairCatalog,
    effect_map: EffectMap | None = None,
    lineage_policy: EffectLineagePolicy | None = None,
) -> RepairPlanResult:
    """Find the first minimal deterministic repair plan that satisfies recovery invariants."""

    chaos_result = run_experiment(
        business_contract,
        chaos_scenario,
        stream,
        effect_map,
        lineage_policy,
    )
    if chaos_result.passed:
        raise ValueError("repair synthesis requires chaos to fail the business contract first")

    baseline = list(chaos_result.replay.mutated_events)
    searched = 0
    last_state = project_business_state(baseline, effect_map, lineage_policy)
    last_results = verify_contract(recovery_contract, last_state)
    last_score = reliability_score(last_results)

    max_length = min(catalog.max_plan_length, len(catalog.candidates))
    for plan_length in range(1, max_length + 1):
        for candidate_indexes in permutations(range(len(catalog.candidates)), plan_length):
            searched += 1
            candidates = [catalog.candidates[index] for index in candidate_indexes]
            generated = _generate_repair_events(candidates, searched)
            timeline = [*baseline, *generated]

            try:
                state = project_business_state(timeline, effect_map, lineage_policy)
            except ValueError:
                continue

            results = verify_contract(recovery_contract, state)
            score = reliability_score(results)
            last_state = state
            last_results = results
            last_score = score

            if all(result.passed for result in results):
                return RepairPlanResult(
                    chaos=chaos_result,
                    catalog=catalog.name,
                    status=RepairStatus.found,
                    searched_plan_count=searched,
                    selected_candidate_names=[candidate.name for candidate in candidates],
                    generated_events=generated,
                    projected_state=state,
                    invariant_results=results,
                    score=score,
                )

    return RepairPlanResult(
        chaos=chaos_result,
        catalog=catalog.name,
        status=RepairStatus.not_found,
        searched_plan_count=searched,
        selected_candidate_names=[],
        generated_events=[],
        projected_state=last_state,
        invariant_results=last_results,
        score=last_score,
    )


def _generate_repair_events(
    candidates: list[RepairCandidate],
    plan_ordinal: int,
) -> list[BusinessEvent]:
    events: list[BusinessEvent] = []
    for step, candidate in enumerate(candidates, start=1):
        slug = _slug(candidate.name)
        events.append(
            BusinessEvent(
                event_id=f"repair-{plan_ordinal:04d}-{step:02d}-{slug}",
                event_type=candidate.event_type,
                payload=candidate.payload,
            )
        )
    return events


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in normalized.split("-") if part) or "candidate"
