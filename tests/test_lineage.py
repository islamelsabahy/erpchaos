import pytest

from erpchaos.effects import EffectMap
from erpchaos.events import BusinessEvent
from erpchaos.lineage import EffectLineagePolicy, project_compensation_lineage


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


def _policy() -> EffectLineagePolicy:
    return EffectLineagePolicy.model_validate(
        {
            "schema": "erpchaos.effect-lineage.v1",
            "name": "Payment compensation lineage",
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


def _event(event_id: str, event_type: str, target: str | None = None) -> BusinessEvent:
    payload = {} if target is None else {"compensates_event_id": target}
    return BusinessEvent(event_id=event_id, event_type=event_type, payload=payload)


def test_correct_duplicate_compensation_leaves_original_active() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.received#dup1", "payment.received"),
        _event("payment.reversed", "payment.reversed", "payment.received#dup1"),
    ]

    state = project_compensation_lineage(events, _effect_map(), _policy())
    payment = state["lineage"]["payment"]

    assert payment["valid"] is True
    assert payment["origin_count"] == 2
    assert payment["compensation_count"] == 1
    assert payment["linked_compensation_count"] == 1
    assert payment["active_origin_ids"] == ["payment.received"]
    assert payment["compensated_origin_ids"] == ["payment.received#dup1"]


def test_wrong_but_structurally_valid_target_remains_visible_to_contracts() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.received#dup1", "payment.received"),
        _event("payment.reversed", "payment.reversed", "payment.received"),
    ]

    state = project_compensation_lineage(events, _effect_map(), _policy())
    payment = state["lineage"]["payment"]

    assert payment["valid"] is True
    assert payment["active_origin_ids"] == ["payment.received#dup1"]
    assert payment["compensated_origin_ids"] == ["payment.received"]


def test_missing_compensation_reference_is_invalid() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.reversed", "payment.reversed"),
    ]

    payment = project_compensation_lineage(events, _effect_map(), _policy())["lineage"][
        "payment"
    ]

    assert payment["missing_reference_count"] == 1
    assert payment["orphan_compensation_count"] == 1
    assert payment["valid"] is False


def test_unknown_compensation_target_is_invalid() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.reversed", "payment.reversed", "unknown-payment"),
    ]

    payment = project_compensation_lineage(events, _effect_map(), _policy())["lineage"][
        "payment"
    ]

    assert payment["unknown_reference_count"] == 1
    assert payment["valid"] is False


def test_future_compensation_target_is_invalid() -> None:
    events = [
        _event("payment.reversed", "payment.reversed", "payment.received"),
        _event("payment.received", "payment.received"),
    ]

    payment = project_compensation_lineage(events, _effect_map(), _policy())["lineage"][
        "payment"
    ]

    assert payment["future_reference_count"] == 1
    assert payment["valid"] is False


def test_compensation_cannot_target_another_compensation() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.reversed.1", "payment.reversed", "payment.received"),
        _event("payment.reversed.2", "payment.reversed", "payment.reversed.1"),
    ]

    payment = project_compensation_lineage(events, _effect_map(), _policy())["lineage"][
        "payment"
    ]

    assert payment["non_origin_reference_count"] == 1
    assert payment["valid"] is False


def test_origin_cannot_be_compensated_twice() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.reversed.1", "payment.reversed", "payment.received"),
        _event("payment.reversed.2", "payment.reversed", "payment.received"),
    ]

    payment = project_compensation_lineage(events, _effect_map(), _policy())["lineage"][
        "payment"
    ]

    assert payment["linked_compensation_count"] == 1
    assert payment["duplicate_compensation_count"] == 1
    assert payment["valid"] is False


def test_lineage_requires_unique_event_ids() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.received", "payment.received"),
    ]

    with pytest.raises(ValueError, match="unique event IDs"):
        project_compensation_lineage(events, _effect_map(), _policy())


def test_lineage_v1_rejects_non_unit_effect_contributions() -> None:
    effect_map = EffectMap.model_validate(
        {
            "schema": "erpchaos.effect-map.v1",
            "name": "Non-unit payment effect",
            "effects": {
                "payment": {
                    "contributions": {
                        "payment.received": 2,
                        "payment.reversed": -1,
                    }
                }
            },
        }
    )

    with pytest.raises(ValueError, match="unit contributions"):
        project_compensation_lineage([], effect_map, _policy())


def test_lineage_requires_rules_for_every_negative_contribution() -> None:
    effect_map = EffectMap.model_validate(
        {
            "schema": "erpchaos.effect-map.v1",
            "name": "Payment effects",
            "effects": {
                "payment": {
                    "contributions": {
                        "payment.received": 1,
                        "payment.reversed": -1,
                        "payment.chargeback": -1,
                    }
                }
            },
        }
    )

    with pytest.raises(ValueError, match="missing compensation rules"):
        project_compensation_lineage([], effect_map, _policy())


def test_projection_is_deterministic() -> None:
    events = [
        _event("payment.received", "payment.received"),
        _event("payment.received#dup1", "payment.received"),
        _event("payment.reversed", "payment.reversed", "payment.received#dup1"),
    ]

    first = project_compensation_lineage(events, _effect_map(), _policy())
    second = project_compensation_lineage(events, _effect_map(), _policy())

    assert first == second
