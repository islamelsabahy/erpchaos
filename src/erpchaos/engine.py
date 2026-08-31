from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from erpchaos.models import BusinessReliabilityContract, Invariant, Operator


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    actual: Any
    expected: Any
    severity: str
    expected_path: str | None = None


def _resolve_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def _safe_resolve_path(payload: dict[str, Any], path: str) -> Any:
    try:
        return _resolve_path(payload, path)
    except KeyError:
        return None


def _evaluate(invariant: Invariant, payload: dict[str, Any]) -> InvariantResult:
    actual = _safe_resolve_path(payload, invariant.path)
    expected = invariant.expected

    if invariant.operator in {Operator.before, Operator.after}:
        assert invariant.expected_path is not None
        expected = _safe_resolve_path(payload, invariant.expected_path)

    if invariant.operator == Operator.equals:
        passed = actual == expected
    elif invariant.operator == Operator.not_equals:
        passed = actual != expected
    elif invariant.operator == Operator.lte:
        passed = actual is not None and actual <= expected
    elif invariant.operator == Operator.gte:
        passed = actual is not None and actual >= expected
    elif invariant.operator == Operator.before:
        passed = actual is not None and expected is not None and actual < expected
    elif invariant.operator == Operator.after:
        passed = actual is not None and expected is not None and actual > expected
    else:
        raise ValueError(f"Unsupported operator: {invariant.operator}")

    return InvariantResult(
        name=invariant.name,
        passed=passed,
        actual=actual,
        expected=expected,
        severity=invariant.severity.value,
        expected_path=invariant.expected_path,
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
