from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from erpchaos.models import Severity
from erpchaos.policy import Finding


class BaselineClassification(StrEnum):
    known = "KNOWN"
    new = "NEW"
    resolved = "RESOLVED"
    regressed = "REGRESSED"


_SEVERITY_RANK = {
    Severity.low: 1,
    Severity.medium: 2,
    Severity.high: 3,
    Severity.critical: 4,
}


class BaselineEntry(BaseModel):
    fingerprint: str
    rule_id: str
    transaction: str
    invariant_name: str
    invariant_path: str
    severity: Severity


class ReliabilityBaseline(BaseModel):
    schema_version: str = Field(default="erpchaos.reliability-baseline.v1", alias="schema")
    name: str
    entries: list[BaselineEntry]

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def unique_fingerprints(self) -> ReliabilityBaseline:
        fingerprints = [entry.fingerprint for entry in self.entries]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("baseline fingerprints must be unique")
        return self


class BaselineException(BaseModel):
    fingerprint: str
    owner: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expires_on: date


class BaselineExceptionDocument(BaseModel):
    schema_version: str = Field(default="erpchaos.baseline-exceptions.v1", alias="schema")
    exceptions: list[BaselineException]

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def unique_fingerprints(self) -> BaselineExceptionDocument:
        fingerprints = [item.fingerprint for item in self.exceptions]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("exception fingerprints must be unique")
        return self


class BaselineComparisonItem(BaseModel):
    fingerprint: str
    rule_id: str
    classification: BaselineClassification
    baseline_severity: Severity | None = None
    current_severity: Severity | None = None
    accepted_by_exception: bool = False
    exception_owner: str | None = None
    exception_expires_on: date | None = None


class BaselineComparisonReport(BaseModel):
    schema_version: str = Field(default="erpchaos.baseline-comparison.v1", alias="schema")
    baseline_name: str
    evaluation_date: date
    status: str
    items: list[BaselineComparisonItem]
    new_count: int
    regressed_count: int
    expired_exception_count: int

    model_config = {"populate_by_name": True, "extra": "forbid"}


def finding_fingerprint(finding: Finding) -> str:
    identity = "\n".join(
        (
            finding.rule_id,
            finding.transaction,
            finding.invariant_name,
            finding.invariant_path,
        )
    ).encode()
    return hashlib.sha256(identity).hexdigest()


def capture_baseline(name: str, findings: list[Finding]) -> ReliabilityBaseline:
    entries = [
        BaselineEntry(
            fingerprint=finding_fingerprint(finding),
            rule_id=finding.rule_id,
            transaction=finding.transaction,
            invariant_name=finding.invariant_name,
            invariant_path=finding.invariant_path,
            severity=finding.severity,
        )
        for finding in findings
    ]
    entries.sort(key=lambda item: item.fingerprint)
    return ReliabilityBaseline(name=name, entries=entries)


def compare_baseline(
    baseline: ReliabilityBaseline,
    findings: list[Finding],
    *,
    evaluation_date: date,
    exceptions: BaselineExceptionDocument | None = None,
) -> BaselineComparisonReport:
    baseline_by_fingerprint = {entry.fingerprint: entry for entry in baseline.entries}
    current_by_fingerprint = {finding_fingerprint(item): item for item in findings}
    exception_by_fingerprint = {
        item.fingerprint: item for item in (exceptions.exceptions if exceptions else [])
    }
    items: list[BaselineComparisonItem] = []
    expired_exception_count = 0

    for fingerprint in sorted(set(baseline_by_fingerprint) | set(current_by_fingerprint)):
        previous = baseline_by_fingerprint.get(fingerprint)
        current = current_by_fingerprint.get(fingerprint)
        exception = exception_by_fingerprint.get(fingerprint)

        if previous is None and current is not None:
            classification = BaselineClassification.new
            rule_id = current.rule_id
        elif previous is not None and current is None:
            classification = BaselineClassification.resolved
            rule_id = previous.rule_id
        else:
            assert previous is not None and current is not None
            classification = (
                BaselineClassification.regressed
                if _SEVERITY_RANK[current.severity] > _SEVERITY_RANK[previous.severity]
                else BaselineClassification.known
            )
            rule_id = current.rule_id

        accepted = False
        if exception is not None and classification is BaselineClassification.known:
            if exception.expires_on < evaluation_date:
                expired_exception_count += 1
            else:
                accepted = True

        items.append(
            BaselineComparisonItem(
                fingerprint=fingerprint,
                rule_id=rule_id,
                classification=classification,
                baseline_severity=previous.severity if previous else None,
                current_severity=current.severity if current else None,
                accepted_by_exception=accepted,
                exception_owner=exception.owner if exception else None,
                exception_expires_on=exception.expires_on if exception else None,
            )
        )

    blocking = [
        item
        for item in items
        if item.classification in {BaselineClassification.new, BaselineClassification.regressed}
    ]
    status = "FAIL" if blocking or expired_exception_count else "PASS"
    return BaselineComparisonReport(
        baseline_name=baseline.name,
        evaluation_date=evaluation_date,
        status=status,
        items=items,
        new_count=sum(item.classification is BaselineClassification.new for item in items),
        regressed_count=sum(
            item.classification is BaselineClassification.regressed for item in items
        ),
        expired_exception_count=expired_exception_count,
    )


def accepted_known_fingerprints(report: BaselineComparisonReport) -> set[str]:
    return {
        item.fingerprint
        for item in report.items
        if item.classification is BaselineClassification.known and item.accepted_by_exception
    }


def filter_policy_findings(
    findings: list[Finding], report: BaselineComparisonReport
) -> list[Finding]:
    accepted = accepted_known_fingerprints(report)
    return [item for item in findings if finding_fingerprint(item) not in accepted]


def canonical_baseline_json(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
