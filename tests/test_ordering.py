import pytest
from pydantic import ValidationError

from erpchaos.engine import verify_contract
from erpchaos.models import BusinessReliabilityContract, Invariant, Operator, Severity


def _contract() -> BusinessReliabilityContract:
    return BusinessReliabilityContract(
        name="ordering",
        transaction="property-sale-event-history",
        invariants=[
            Invariant(
                name="finance-before-payment",
                path="history.types.finance_approved.first_position",
                operator=Operator.before,
                expected_path="history.types.payment_received.first_position",
                severity=Severity.critical,
            )
        ],
    )


def test_before_operator_passes_when_sequence_is_valid() -> None:
    state = {
        "history": {
            "types": {
                "finance_approved": {"first_position": 2},
                "payment_received": {"first_position": 3},
            }
        }
    }

    result = verify_contract(_contract(), state)[0]

    assert result.passed is True
    assert result.actual == 2
    assert result.expected == 3


def test_before_operator_fails_when_payment_happens_first() -> None:
    state = {
        "history": {
            "types": {
                "finance_approved": {"first_position": 3},
                "payment_received": {"first_position": 1},
            }
        }
    }

    result = verify_contract(_contract(), state)[0]

    assert result.passed is False
    assert result.actual == 3
    assert result.expected == 1


def test_ordering_operator_requires_expected_path() -> None:
    with pytest.raises(ValidationError):
        Invariant(
            name="invalid-ordering-rule",
            path="history.types.finance_approved.first_position",
            operator=Operator.before,
            severity=Severity.high,
        )
