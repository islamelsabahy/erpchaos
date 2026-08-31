from erpchaos.engine import reliability_score, verify_contract
from erpchaos.models import BusinessReliabilityContract


def test_healthy_transaction_scores_100() -> None:
    contract = BusinessReliabilityContract.model_validate(
        {
            "name": "demo",
            "transaction": "sale",
            "invariants": [
                {
                    "name": "one-payment",
                    "path": "payment.records",
                    "expected": 1,
                    "severity": "critical",
                },
                {
                    "name": "approved",
                    "path": "finance.approved",
                    "expected": True,
                    "severity": "high",
                },
            ],
        }
    )
    results = verify_contract(
        contract,
        {"payment": {"records": 1}, "finance": {"approved": True}},
    )

    assert all(result.passed for result in results)
    assert reliability_score(results) == 100


def test_critical_failure_reduces_score() -> None:
    contract = BusinessReliabilityContract.model_validate(
        {
            "name": "demo",
            "transaction": "sale",
            "invariants": [
                {
                    "name": "one-payment",
                    "path": "payment.records",
                    "expected": 1,
                    "severity": "critical",
                },
                {
                    "name": "approved",
                    "path": "finance.approved",
                    "expected": True,
                    "severity": "high",
                },
            ],
        }
    )
    results = verify_contract(
        contract,
        {"payment": {"records": 3}, "finance": {"approved": True}},
    )

    assert results[0].passed is False
    assert reliability_score(results) == 33
