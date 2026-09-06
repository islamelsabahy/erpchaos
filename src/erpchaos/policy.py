from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from erpchaos.engine import InvariantResult
from erpchaos.models import BusinessReliabilityContract, Severity


class FindingSourceKind(StrEnum):
    brc = "brc"


class PolicyStatus(StrEnum):
    passed = "PASS"
    failed = "FAIL"


_SEVERITY_RANK = {
    Severity.low: 1,
    Severity.medium: 2,
    Severity.high: 3,
    Severity.critical: 4,
}


class PolicyGate(BaseModel):
    schema_version: str = Field(default="erpchaos.policy-gate.v1", alias="schema")
    name: str
    fail_on_or_above: Severity = Severity.high
    ignored_rule_ids: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "extra": "forbid"}


class Finding(BaseModel):
    rule_id: str
    source_kind: FindingSourceKind
    contract_name: str
    transaction: str
    invariant_name: str
    invariant_path: str
    severity: Severity
    message: str
    actual: Any = None
    expected: Any = None
    source_uri: str | None = None


class FindingDocument(BaseModel):
    schema_version: str = Field(default="erpchaos.findings.v1", alias="schema")
    findings: list[Finding]

    model_config = {"populate_by_name": True}


class PolicyEvaluation(BaseModel):
    schema_version: str = Field(default="erpchaos.policy-evaluation.v1", alias="schema")
    policy_name: str
    status: PolicyStatus
    finding_count: int
    violating_finding_count: int
    findings: list[Finding]

    model_config = {"populate_by_name": True}


def _rule_id(transaction: str, invariant_name: str, invariant_path: str) -> str:
    identity = f"{transaction}\n{invariant_name}\n{invariant_path}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:12]
    return f"ERPCHAOS-BRC-{digest}"


def findings_from_invariants(
    contract: BusinessReliabilityContract,
    results: list[InvariantResult],
    *,
    source_uri: str | None = None,
) -> list[Finding]:
    if len(contract.invariants) != len(results):
        raise ValueError("contract invariant count does not match result count")

    findings: list[Finding] = []
    for invariant, result in zip(contract.invariants, results, strict=True):
        if result.passed:
            continue
        severity = Severity(result.severity)
        finding = Finding(
            rule_id=_rule_id(contract.transaction, invariant.name, invariant.path),
            source_kind=FindingSourceKind.brc,
            contract_name=contract.name,
            transaction=contract.transaction,
            invariant_name=invariant.name,
            invariant_path=invariant.path,
            severity=severity,
            message=(
                f"Business invariant '{invariant.name}' failed: "
                f"expected {result.expected!r}, got {result.actual!r}."
            ),
            actual=result.actual,
            expected=result.expected,
            source_uri=source_uri,
        )
        findings.append(finding)

    return sorted(findings, key=lambda item: (item.rule_id, item.message))


def evaluate_policy(policy: PolicyGate, findings: list[Finding]) -> PolicyEvaluation:
    ignored = set(policy.ignored_rule_ids)
    violating = [
        finding
        for finding in findings
        if finding.rule_id not in ignored
        and _SEVERITY_RANK[finding.severity] >= _SEVERITY_RANK[policy.fail_on_or_above]
    ]
    ordered = sorted(findings, key=lambda item: (item.rule_id, item.message))
    return PolicyEvaluation(
        policy_name=policy.name,
        status=PolicyStatus.failed if violating else PolicyStatus.passed,
        finding_count=len(ordered),
        violating_finding_count=len(violating),
        findings=ordered,
    )


def canonical_json(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
