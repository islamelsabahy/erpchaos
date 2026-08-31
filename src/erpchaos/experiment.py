from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from erpchaos.effects import EffectMap
from erpchaos.engine import InvariantResult, reliability_score, verify_contract
from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.models import BusinessReliabilityContract
from erpchaos.projection import project_business_state
from erpchaos.replay import ReplayResult, replay


@dataclass(frozen=True)
class ExperimentResult:
    replay: ReplayResult
    projected_state: dict[str, Any]
    invariant_results: list[InvariantResult]
    score: int

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.invariant_results)


def run_experiment(
    contract: BusinessReliabilityContract,
    scenario: ChaosScenario,
    stream: EventStream,
    effect_map: EffectMap | None = None,
) -> ExperimentResult:
    """Replay chaos, project business state, then evaluate the BRC."""

    replay_result = replay(stream, scenario)
    projected_state = project_business_state(replay_result.mutated_events, effect_map)
    invariant_results = verify_contract(contract, projected_state)

    return ExperimentResult(
        replay=replay_result,
        projected_state=projected_state,
        invariant_results=invariant_results,
        score=reliability_score(invariant_results),
    )
