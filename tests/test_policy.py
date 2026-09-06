from __future__ import annotations

import json

from erpchaos.engine import verify_contract
from erpchaos.models import BusinessReliabilityContract
from erpchaos.policy import (
    FindingDocument,
    PolicyGate,
    PolicyStatus,
    canonical_json,
    evaluate_policy,
    findings_from_invariants,
)
from erpchaos.sarif import canonical_sarif_json, render_sarif


def _contract() -> BusinessReliabilityContract:
    return BusinessReliabilityContract.model_validate(
        {
            "name": "Property Sale Reliability Contract",
            "version": "1",
            "transaction": "property-sale",
            "invariants": [
                {
                    "name": "payment-idempotency",
                    "path": "payment.posted_records",
                    "operator": "equals",
                    "expected": 1,
                    "severity": "critical",
                },
                {
                    "name": "commission-idempotency",
                    "path": "commission.records",
                    "operator": "equals",
                    "expected": 1,
                    "severity": "high",
                },
                {
                    "name": "audit-note",
                    "path": "audit.notes",
                    "operator": "lte",
                    "expected": 1,
                    "severity": "medium",
                },
            ],
        }
    )


def _findings():
    contract = _contract()
    state = {
        "payment": {"posted_records": 2},
        "commission": {"records": 2},
        "audit": {"notes": 2},
    }
    results = verify_contract(contract, state)
    return findings_from_invariants(contract, results, source_uri="contract.yaml")


def test_findings_are_only_failures_and_stably_ordered() -> None:
    findings = _findings()

    assert len(findings) == 3
    assert [finding.rule_id for finding in findings] == sorted(
        finding.rule_id for finding in findings
    )
    assert all(finding.source_uri == "contract.yaml" for finding in findings)
    assert all(finding.rule_id.startswith("ERPCHAOS-BRC-") for finding in findings)


def test_policy_threshold_blocks_high_and_critical_but_not_medium() -> None:
    policy = PolicyGate(name="strict", fail_on_or_above="high")
    evaluation = evaluate_policy(policy, _findings())

    assert evaluation.status is PolicyStatus.failed
    assert evaluation.finding_count == 3
    assert evaluation.violating_finding_count == 2


def test_policy_can_ignore_one_stable_rule() -> None:
    findings = _findings()
    high_or_critical = [
        finding for finding in findings if finding.severity.value in {"high", "critical"}
    ]
    policy = PolicyGate(
        name="one exception",
        fail_on_or_above="critical",
        ignored_rule_ids=[
            finding.rule_id
            for finding in findings
            if finding.severity.value == "critical"
        ],
    )
    evaluation = evaluate_policy(policy, findings)

    assert len(high_or_critical) == 2
    assert evaluation.status is PolicyStatus.passed
    assert evaluation.violating_finding_count == 0


def test_finding_json_is_byte_stable() -> None:
    document = FindingDocument(findings=_findings())
    first = canonical_json(document)
    second = canonical_json(document)

    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["schema"] == "erpchaos.findings.v1"


def test_sarif_is_21_and_byte_stable() -> None:
    findings = _findings()
    first = canonical_sarif_json(findings)
    second = canonical_sarif_json(list(reversed(findings)))
    payload = json.loads(first)

    assert first == second
    assert payload["version"] == "2.1.0"
    assert payload["$schema"].endswith("sarif-2.1.0.json")
    assert len(payload["runs"]) == 1
    assert len(payload["runs"][0]["results"]) == 3


def test_sarif_severity_mapping_and_rules_are_stable() -> None:
    payload = render_sarif(_findings())
    run = payload["runs"][0]
    levels = {result["properties"]["severity"]: result["level"] for result in run["results"]}
    rule_ids = [rule["id"] for rule in run["tool"]["driver"]["rules"]]

    assert levels == {"critical": "error", "high": "error", "medium": "warning"}
    assert rule_ids == sorted(rule_ids)
