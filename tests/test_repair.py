import pytest
from pydantic import ValidationError

from erpchaos.effects import EffectMap
from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import RecoveryContract
from erpchaos.repair import RepairCatalog, RepairStatus, synthesize_repair_plan


def _stream() -> EventStream:
    return EventStream.model_validate(
        {
            "transaction_id": "sale-001",
            "events": [
                {
                    "event_id": "payment.received",
                    "event_type": "payment.received",
                    "payload": {},
                }
            ],
        }
    )


def _chaos() -> ChaosScenario:
    return ChaosScenario.model_validate(
        {
            "name": "Duplicate payment callback",
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
                        "payment.reversed": {"target_field": "compensates_event_id"}
                    }
                }
            },
        }
    )


def _business_contract() -> BusinessReliabilityContract:
    return BusinessReliabilityContract.model_validate(
        {
            "name": "Payment reliability",
            "transaction": "payment",
            "invariants": [
                {
                    "name": "one-effective-payment",
                    "path": "effects.payment.balance",
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
            "name": "Causal payment recovery",
            "transaction": "payment-recovery",
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
                    "name": "original-payment-remains-active",
                    "path": "lineage.payment.active_origin_ids",
                    "operator": "equals",
                    "expected": ["payment.received"],
                    "severity": "critical",
                },
                {
                    "name": "duplicate-payment-is-compensated",
                    "path": "lineage.payment.compensated_origin_ids",
                    "operator": "equals",
                    "expected": ["payment.received#dup1"],
                    "severity": "critical",
                },
            ],
        }
    )


def _catalog(include_correct: bool = True) -> RepairCatalog:
    candidates = [
        {
            "name": "reverse-original-payment",
            "event_type": "payment.reversed",
            "payload": {"compensates_event_id": "payment.received"},
        }
    ]
    if include_correct:
        candidates.append(
            {
                "name": "reverse-duplicate-payment",
                "event_type": "payment.reversed",
                "payload": {"compensates_event_id": "payment.received#dup1"},
            }
        )
    return RepairCatalog.model_validate(
        {
            "schema": "erpchaos.repair-catalog.v1",
            "name": "Duplicate payment repairs",
            "max_plan_length": 1,
            "candidates": candidates,
        }
    )


def _synthesize(catalog: RepairCatalog):
    return synthesize_repair_plan(
        _business_contract(),
        _chaos(),
        _stream(),
        _recovery_contract(),
        catalog,
        _effect_map(),
        _lineage_policy(),
    )


def test_selects_minimal_correct_causal_repair() -> None:
    result = _synthesize(_catalog())

    assert result.status is RepairStatus.found
    assert result.passed is True
    assert result.plan_length == 1
    assert result.searched_plan_count == 2
    assert result.selected_candidate_names == ["reverse-duplicate-payment"]
    assert result.score == 100
    assert result.projected_state["effects"]["payment"]["balance"] == 1
    assert result.projected_state["lineage"]["payment"]["active_origin_ids"] == [
        "payment.received"
    ]


def test_wrong_target_only_catalog_returns_no_repair_found() -> None:
    result = _synthesize(_catalog(include_correct=False))

    assert result.status is RepairStatus.not_found
    assert result.passed is False
    assert result.plan_length is None
    assert result.searched_plan_count == 1
    assert result.selected_candidate_names == []


def test_synthesis_is_deterministic() -> None:
    first = _synthesize(_catalog())
    second = _synthesize(_catalog())

    assert first.status == second.status
    assert first.searched_plan_count == second.searched_plan_count
    assert first.selected_candidate_names == second.selected_candidate_names
    assert first.generated_events == second.generated_events
    assert first.projected_state == second.projected_state


def test_catalog_rejects_duplicate_candidate_names() -> None:
    with pytest.raises(ValidationError, match="candidate names must be unique"):
        RepairCatalog.model_validate(
            {
                "schema": "erpchaos.repair-catalog.v1",
                "name": "Invalid catalog",
                "max_plan_length": 1,
                "candidates": [
                    {"name": "same", "event_type": "payment.reversed"},
                    {"name": "same", "event_type": "payment.reversed"},
                ],
            }
        )


def test_catalog_rejects_search_space_over_budget() -> None:
    with pytest.raises(ValidationError, match="search space exceeds max_evaluations"):
        RepairCatalog.model_validate(
            {
                "schema": "erpchaos.repair-catalog.v1",
                "name": "Oversized search",
                "max_plan_length": 3,
                "max_evaluations": 5,
                "candidates": [
                    {"name": "one", "event_type": "repair.one"},
                    {"name": "two", "event_type": "repair.two"},
                    {"name": "three", "event_type": "repair.three"},
                ],
            }
        )


def test_repair_synthesis_rejects_non_failing_chaos() -> None:
    healthy_contract = BusinessReliabilityContract.model_validate(
        {
            "name": "Allows duplicate payment",
            "transaction": "payment",
            "invariants": [
                {
                    "name": "two-payments-allowed",
                    "path": "effects.payment.balance",
                    "operator": "equals",
                    "expected": 2,
                    "severity": "critical",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="requires chaos to fail"):
        synthesize_repair_plan(
            healthy_contract,
            _chaos(),
            _stream(),
            _recovery_contract(),
            _catalog(),
            _effect_map(),
            _lineage_policy(),
        )
