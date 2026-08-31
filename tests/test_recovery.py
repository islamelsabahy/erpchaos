from pathlib import Path

import yaml

from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import (
    RecoveryContract,
    RecoveryScenario,
    RecoveryStatus,
    run_recovery_experiment,
)

EXAMPLES = Path("examples/real-estate")


def _load(path: str) -> dict[str, object]:
    return yaml.safe_load((EXAMPLES / path).read_text(encoding="utf-8"))


def _inputs() -> tuple[
    BusinessReliabilityContract,
    ChaosScenario,
    EventStream,
    RecoveryContract,
]:
    return (
        BusinessReliabilityContract.model_validate(_load("property-sale.events.brc.yaml")),
        ChaosScenario.model_validate(_load("duplicate-payment.scenario.yaml")),
        EventStream.model_validate(_load("property-sale.events.yaml")),
        RecoveryContract.model_validate(_load("payment-recovery.brc.yaml")),
    )


def test_successful_recovery_has_ttbc_one_and_full_score() -> None:
    contract, chaos, stream, recovery_contract = _inputs()
    scenario = RecoveryScenario.model_validate(_load("payment-recovered.recovery.yaml"))

    result = run_recovery_experiment(contract, chaos, stream, recovery_contract, scenario)

    assert result.status is RecoveryStatus.recovered
    assert result.score == 100
    assert result.ttbc_steps == 1
    assert result.regressed_after_recovery is False
    assert result.passed is True
    assert result.checkpoints[-1].passed is True


def test_recovery_can_regress_after_first_consistent_checkpoint() -> None:
    contract, chaos, stream, recovery_contract = _inputs()
    scenario = RecoveryScenario.model_validate(_load("payment-regressed.recovery.yaml"))

    result = run_recovery_experiment(contract, chaos, stream, recovery_contract, scenario)

    assert result.status is RecoveryStatus.partially_recovered
    assert result.score == 50
    assert result.ttbc_steps == 1
    assert result.regressed_after_recovery is True
    assert [checkpoint.passed for checkpoint in result.checkpoints] == [True, False]


def test_unrecovered_path_has_zero_score_and_no_ttbc() -> None:
    contract, chaos, stream, recovery_contract = _inputs()
    scenario = RecoveryScenario.model_validate(_load("payment-unrecovered.recovery.yaml"))

    result = run_recovery_experiment(contract, chaos, stream, recovery_contract, scenario)

    assert result.status is RecoveryStatus.unrecovered
    assert result.score == 0
    assert result.ttbc_steps is None
    assert result.regressed_after_recovery is False
    assert result.passed is False


def test_recovery_result_is_deterministic() -> None:
    contract, chaos, stream, recovery_contract = _inputs()
    scenario = RecoveryScenario.model_validate(_load("payment-recovered.recovery.yaml"))

    first = run_recovery_experiment(contract, chaos, stream, recovery_contract, scenario)
    second = run_recovery_experiment(contract, chaos, stream, recovery_contract, scenario)

    assert first == second
