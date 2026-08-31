import pytest
from pydantic import ValidationError

from erpchaos.concurrency import ConcurrencyScenario, run_concurrency


def _scenario(second_outcome: str = "reservation.succeeded") -> ConcurrencyScenario:
    return ConcurrencyScenario.model_validate(
        {
            "name": "unit reservation race",
            "resource_key": "unit:A-203",
            "success_event_type": "reservation.succeeded",
            "max_successes": 1,
            "streams": [
                {
                    "transaction_id": "reservation-A",
                    "events": [
                        {"event_id": "A-1", "event_type": "reservation.requested"},
                        {"event_id": "A-2", "event_type": "inventory.checked"},
                        {"event_id": "A-3", "event_type": "reservation.succeeded"},
                    ],
                },
                {
                    "transaction_id": "reservation-B",
                    "events": [
                        {"event_id": "B-1", "event_type": "reservation.requested"},
                        {"event_id": "B-2", "event_type": "inventory.checked"},
                        {"event_id": "B-3", "event_type": second_outcome},
                    ],
                },
            ],
            "schedule": [
                "reservation-A",
                "reservation-B",
                "reservation-A",
                "reservation-B",
                "reservation-A",
                "reservation-B",
            ],
        }
    )


def test_concurrency_interleaving_is_deterministic() -> None:
    scenario = _scenario()

    first = run_concurrency(scenario)
    second = run_concurrency(scenario)

    expected = ["A-1", "B-1", "A-2", "B-2", "A-3", "B-3"]
    assert [item.event.event_id for item in first.timeline] == expected
    assert [item.event.event_id for item in second.timeline] == expected


def test_double_reservation_fails_exclusivity() -> None:
    result = run_concurrency(_scenario())

    assert result.passed is False
    assert result.successful_transactions == ["reservation-A", "reservation-B"]
    assert result.invariant_result.actual == 2
    assert result.score == 0


def test_single_winner_passes_exclusivity() -> None:
    result = run_concurrency(_scenario("reservation.rejected"))

    assert result.passed is True
    assert result.successful_transactions == ["reservation-A"]
    assert result.invariant_result.actual == 1
    assert result.score == 100


def test_schedule_must_consume_each_event_exactly_once() -> None:
    payload = _scenario().model_dump()
    payload["schedule"] = payload["schedule"][:-1]

    with pytest.raises(ValidationError, match="consume every event exactly once"):
        ConcurrencyScenario.model_validate(payload)


def test_schedule_rejects_unknown_transaction() -> None:
    payload = _scenario().model_dump()
    payload["schedule"][-1] = "reservation-C"

    with pytest.raises(ValidationError, match="unknown transaction"):
        ConcurrencyScenario.model_validate(payload)
