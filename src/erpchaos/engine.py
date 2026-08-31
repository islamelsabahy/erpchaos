from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from erpchaos.models import BusinessReliabilityContract, Invariant


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    actual: Any
    expected: Any
    severity: str


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def _evaluate(invariant: Invariant, payload: dict[str, Any]) -> InvariantResult:
    try:
        actual = _resolve_path(payload, invariant.path)
    except KeyError:
        actual = None

    if invariant.operator == "equals":
        passed = actual == invariant.expected
    elif invariant.operator == "not_equals":
        passed = actual != invariant.expected
    elif invariant.operator == "lte":
        passed = actual is not None and actual <= invariant.expected
    elif invariant.operator == "gte":
        passed = actual is not None and actual >= invariant.expected
    else:
        raise ValueError(f"Unsupported operator: {invariant.operator}")

    return InvariantResult(
        name=invariant.name,
        passed=passed,
        actual=actual,
        expected=invariant.expected,
        severity=invariant.severity.value,
    )


def verify_contract(
    contract: BusinessReliabilityContract,
    transaction_state: dict[str, Any],
) -> list[InvariantResult]:
    return [_evaluate(invariant, transaction_state) for invariant in contract.invariants]


def reliability_score(results: list[InvariantResult]) -> int:
    if not results:
        return 0
    weights = {"low": 1, "medium": 2, "high": 4, "critical": 8}
    total = sum(weights[result.severity] for result in results)
    earned = sum(weights[result.severity] for result in results if result.passed)
    return round((earned / total) * 100)
