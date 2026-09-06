from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any

from erpchaos.models import Severity
from erpchaos.policy import Finding


_SARIF_LEVEL = {
    Severity.low: "note",
    Severity.medium: "warning",
    Severity.high: "error",
    Severity.critical: "error",
}


def _rule(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.rule_id,
        "name": finding.invariant_name,
        "shortDescription": {"text": finding.invariant_name},
        "fullDescription": {
            "text": f"ERPChaos business reliability invariant for {finding.transaction}."
        },
        "properties": {
            "severity": finding.severity.value,
            "sourceKind": finding.source_kind.value,
        },
    }


def _result(finding: Finding) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ruleId": finding.rule_id,
        "level": _SARIF_LEVEL[finding.severity],
        "message": {"text": finding.message},
        "properties": {
            "actual": finding.actual,
            "expected": finding.expected,
            "contract": finding.contract_name,
            "invariantPath": finding.invariant_path,
            "severity": finding.severity.value,
            "transaction": finding.transaction,
        },
    }
    if finding.source_uri:
        result["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.source_uri},
                }
            }
        ]
    return result


def render_sarif(findings: list[Finding]) -> dict[str, Any]:
    ordered = sorted(findings, key=lambda item: (item.rule_id, item.message))
    unique_rules = {finding.rule_id: finding for finding in ordered}
    rules = [_rule(unique_rules[rule_id]) for rule_id in sorted(unique_rules)]
    results = [_result(finding) for finding in ordered]
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ERPChaos",
                        "informationUri": "https://github.com/islamelsabahy/erpchaos",
                        "semanticVersion": version("erpchaos"),
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def canonical_sarif_json(findings: list[Finding]) -> str:
    return json.dumps(
        render_sarif(findings),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
