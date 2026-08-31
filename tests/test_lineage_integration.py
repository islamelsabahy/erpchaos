from erpchaos.effects import EffectMap
from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
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
                {"event_id": "finance.approved", "event_type": "finance.approved"},
                {"event_id": "payment.received", "event_type": "payment.received"},
                {"event_id": "contract.generated", "event_type": "contract.generated"},
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
            "name": "Payment effects",
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


def _lineage_policy() -> EffectLineagePolicy:
    return EffectLineagePolicy.model_validate(
        {
            "schema": "erpchaos.effect-lineage.v1",
            "name": "Payment lineage",
            "effects": {
                "payment": {
                    "compensation_events": {
                        "payment.reversed": {
                            "target_field": "compensates_event_id",
                        }
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


def _recovery_contract() -> RecoveryContract:
    return RecoveryContract.model_validate(
        {
            "name": "Causal duplicate payment recovery",
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
                    "name": "valid-lineage",
                    "path": "lineage.payment.valid",
                    "operator": "equals",
                    "expected": True,
                    "severity": "critical",
                },
                {
                    "name": "original-remains-active",
                    "path": "lineage.payment.active_origin_ids",
                    "operator": "equals",
                    "expected": ["payment.received"],
                    "severity": "critical",
                },
                {
                    "name": "duplicate-compensated",
                    "path": "lineage.payment.compensated_origin_ids",
                    "operator": "equals",
                    "expected": ["payment.received#dup1"],
                    "severity": "critical",
                },
            ],
        }
    )


def _recovery(target: str) -> RecoveryScenario:
    return RecoveryScenario.model_validate(
        {
            "name": f"Reverse {target}",
            "events": [
                {
                    "event_id": "payment.reversed",
                    "event_type": "payment.reversed",
                    "payload": {"compensates_event_id": target},
                }
            ],
        }
    )


def test_correct_causal_target_recovers_expected_origin() -> None:
    result = run_recovery_experiment(
        _business_contract(),
        _duplicate_payment(),
        _stream(),
        _recovery_contract(),
        _recovery("payment.received#dup1"),
        _effect_map(),
        _lineage_policy(),
    )

    assert result.status is RecoveryStatus.recovered
    assert result.ttbc_steps == 1
    assert result.projected_state["effects"]["payment"]["balance"] == 1
    assert result.projected_state["lineage"]["payment"]["valid"] is True
    assert result.projected_state["lineage"]["payment"]["active_origin_ids"] == [
        "payment.received"
    ]


def test_wrong_causal_target_fails_despite_same_net_balance() -> None:
    result = run_recovery_experiment(
        _business_contract(),
        _duplicate_payment(),
        _stream(),
        _recovery_contract(),
        _recovery("payment.received"),
        _effect_map(),
        _lineage_policy(),
    )

    assert result.projected_state["effects"]["payment"]["balance"] == 1
    assert result.projected_state["lineage"]["payment"]["valid"] is True
    assert result.projected_state["lineage"]["payment"]["active_origin_ids"] == [
        "payment.received#dup1"
    ]
    assert result.status is RecoveryStatus.partially_recovered
    assert result.passed is False
    assert result.ttbc_steps is None
