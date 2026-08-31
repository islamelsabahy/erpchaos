import pytest
from pydantic import ValidationError

from erpchaos.effects import EffectMap, project_effect_ledger
from erpchaos.events import BusinessEvent


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
                },
                "commission": {
                    "contributions": {
                        "commission.created": 1,
                        "commission.voided": -1,
                    }
                },
            },
        }
    )


def _event(event_id: str, event_type: str) -> BusinessEvent:
    return BusinessEvent(event_id=event_id, event_type=event_type)


def test_effect_ledger_projects_net_compensation() -> None:
    events = [
        _event("payment-1", "payment.received"),
        _event("payment-2", "payment.received"),
        _event("reversal-1", "payment.reversed"),
    ]

    state = project_effect_ledger(events, _effect_map())
    payment = state["effects"]["payment"]

    assert payment == {
        "balance": 1,
        "min_balance": 0,
        "max_balance": 2,
        "contribution_count": 3,
        "ever_negative": False,
    }


def test_orphan_reversal_records_negative_history() -> None:
    events = [
        _event("reversal-1", "payment.reversed"),
        _event("payment-1", "payment.received"),
    ]

    state = project_effect_ledger(events, _effect_map())
    payment = state["effects"]["payment"]

    assert payment["balance"] == 0
    assert payment["min_balance"] == -1
    assert payment["ever_negative"] is True


def test_over_compensation_produces_negative_final_balance() -> None:
    events = [
        _event("payment-1", "payment.received"),
        _event("reversal-1", "payment.reversed"),
        _event("reversal-2", "payment.reversed"),
    ]

    state = project_effect_ledger(events, _effect_map())
    payment = state["effects"]["payment"]

    assert payment["balance"] == -1
    assert payment["min_balance"] == -1
    assert payment["ever_negative"] is True


def test_unmapped_events_do_not_change_effect_balance() -> None:
    events = [
        _event("reservation-1", "reservation.created"),
        _event("contract-1", "contract.generated"),
    ]

    state = project_effect_ledger(events, _effect_map())

    assert state["effects"]["payment"]["balance"] == 0
    assert state["effects"]["payment"]["contribution_count"] == 0
    assert state["effects"]["commission"]["balance"] == 0


def test_projection_is_deterministic() -> None:
    events = [
        _event("payment-1", "payment.received"),
        _event("payment-2", "payment.received"),
        _event("reversal-1", "payment.reversed"),
        _event("commission-1", "commission.created"),
    ]

    first = project_effect_ledger(events, _effect_map())
    second = project_effect_ledger(events, _effect_map())

    assert first == second


def test_zero_contribution_is_rejected() -> None:
    payload = _effect_map().model_dump(mode="json", by_alias=True)
    payload["effects"]["payment"]["contributions"]["payment.ignored"] = 0

    with pytest.raises(ValidationError, match="non-zero integers"):
        EffectMap.model_validate(payload)


def test_empty_effect_name_is_rejected() -> None:
    payload = _effect_map().model_dump(mode="json", by_alias=True)
    payload["effects"][""] = payload["effects"].pop("commission")

    with pytest.raises(ValidationError, match="effect names must not be empty"):
        EffectMap.model_validate(payload)
