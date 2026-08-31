from erpchaos.effects import EffectMap
from erpchaos.events import EventStream
from erpchaos.experiment import run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import (
    RecoveryContract,
    RecoveryScenario,
    RecoveryStatus,
    run_recovery_experiment,
)


def _stream() -> EventStream:
    return EventStream.model_validate(
        {
            "transaction_id": "sale-001",
            "events": [
                {"event_id": "reservation.created", "event_type": "reservation.created"},
                {"event_id": "finance.approved", "event_type": "finance.approved"},
                {"event_id": "payment.received", "event_type": "payment.received"},
                {"event_id": "contract.generated", "event_type": "contract.generated"},
                {"event_id": "unit.sold", "event_type": "unit.sold"},
                {"event_id": "commission.created", "event_type": "commission.created"},
            ],
        }
    )


def _duplicate_payment() -> ChaosScenario:
    return ChaosScenario.model_validate(
        {
            "name": "duplicate-payment-callback",
            "faults": [
                {
                    "type": "duplicate_event",
                    "target_event_id": "payment.received",
                    "repeat": 1,
                }
            ],
        }
    )


def _effect_map() -> EffectMap:
    return EffectMap.model_validate(
        {
            "schema": "erpchaos.effect-map.v1",
            "name": "Property sale effects",
            "effects": {
                "payment": {
                    "contributions": {
                        "payment.received": 1,
                        "payment.reversed": -1,
                    }
                }
            },
        }
    )


def _business_contract() -> BusinessReliabilityContract:
    return BusinessReliabilityContract.model_validate(
        {
            "name": "Payment idempotency",
            "transaction": "sale",
            "invariants": [
                {
                    "name": "one-payment-event",
                    "path": "history.types.payment_received.count",
                    "operator": "equals",
                    "expected": 1,
                    "severity": "critical",
                }
            ],
        }
    )


def _effect_recovery_contract() -> RecoveryContract:
    return RecoveryContract.model_validate(
        {
            "name": "Effective payment recovery",
            "transaction": "sale-recovery",
            "contract_type": "recovery",
            "invariants": [
                {
                    "name": "one-effective-payment",
                    "path": "effects.payment.balance",
                    "operator": "equals",
                    "expected": 1,
                    "severity": "critical",
                },
                {
                    "name": "payment-never-negative",
                    "path": "effects.payment.ever_negative",
                    "operator": "equals",
                    "expected": False,
                    "severity": "critical",
                },
            ],
        }
    )


def test_effect_aware_experiment_exposes_business_balance_to_brc() -> None:
    contract = BusinessReliabilityContract.model_validate(
        {
            "name": "Duplicate payment effect",
            "transaction": "sale",
            "invariants": [
                {
                    "name": "two-effective-payments-after-duplicate",
                    "path": "effects.payment.balance",
                    "operator": "equals",
                    "expected": 2,
                    "severity": "critical",
                }
            ],
        }
    )

    result = run_experiment(contract, _duplicate_payment(), _stream(), _effect_map())

    assert result.passed is True
    assert result.projected_state["effects"]["payment"]["balance"] == 2


def test_effect_aware_recovery_restores_one_effective_payment() -> None:
    recovery = RecoveryScenario.model_validate(
        {
            "name": "Reverse duplicate once",
            "events": [
                {"event_id": "payment.reversed", "event_type": "payment.reversed"}
            ],
        }
    )

    result = run_recovery_experiment(
        _business_contract(),
        _duplicate_payment(),
        _stream(),
        _effect_recovery_contract(),
        recovery,
        _effect_map(),
    )

    assert result.status is RecoveryStatus.recovered
    assert result.ttbc_steps == 1
    assert result.regressed_after_recovery is False
    assert result.projected_state["effects"]["payment"]["balance"] == 1


def test_effect_aware_recovery_detects_compensation_regression() -> None:
    recovery = RecoveryScenario.model_validate(
        {
            "name": "Reverse duplicate twice",
            "events": [
                {"event_id": "payment.reversed.1", "event_type": "payment.reversed"},
                {"event_id": "payment.reversed.2", "event_type": "payment.reversed"},
            ],
        }
    )

    result = run_recovery_experiment(
        _business_contract(),
        _duplicate_payment(),
        _stream(),
        _effect_recovery_contract(),
        recovery,
        _effect_map(),
    )

    assert result.status is RecoveryStatus.partially_recovered
    assert result.ttbc_steps == 1
    assert result.regressed_after_recovery is True
    assert result.projected_state["effects"]["payment"]["balance"] == 0
