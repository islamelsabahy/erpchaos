from datetime import date

from erpchaos.baseline import (
    BaselineClassification,
    BaselineException,
    BaselineExceptionDocument,
    canonical_baseline_json,
    capture_baseline,
    compare_baseline,
    finding_fingerprint,
)
from erpchaos.models import Severity
from erpchaos.policy import Finding, FindingSourceKind


def finding(name: str, severity: Severity = Severity.high) -> Finding:
    return Finding(
        rule_id=f"ERPCHAOS-{name}",
        source_kind=FindingSourceKind.brc,
        contract_name="Contract",
        transaction="sale",
        invariant_name=name,
        invariant_path=f"state.{name}",
        severity=severity,
        message=f"{name} failed",
    )


def test_known_and_resolved_findings() -> None:
    first = finding("one")
    second = finding("two")
    baseline = capture_baseline("legacy", [first, second])
    report = compare_baseline(baseline, [first], evaluation_date=date(2026, 9, 7))
    assert [item.classification for item in report.items] == [
        BaselineClassification.resolved,
        BaselineClassification.known,
    ] or [item.classification for item in report.items] == [
        BaselineClassification.known,
        BaselineClassification.resolved,
    ]
    assert report.status == "PASS"


def test_new_finding_fails() -> None:
    baseline = capture_baseline("legacy", [])
    report = compare_baseline(
        baseline,
        [finding("new")],
        evaluation_date=date(2026, 9, 7),
    )
    assert report.items[0].classification is BaselineClassification.new
    assert report.status == "FAIL"


def test_severity_increase_is_regression() -> None:
    low = finding("payment", Severity.medium)
    high = finding("payment", Severity.critical)
    baseline = capture_baseline("legacy", [low])
    report = compare_baseline(baseline, [high], evaluation_date=date(2026, 9, 7))
    assert report.items[0].classification is BaselineClassification.regressed
    assert report.status == "FAIL"


def test_exact_non_expired_exception_accepts_new_finding() -> None:
    current = finding("new")
    baseline = capture_baseline("legacy", [])
    exceptions = BaselineExceptionDocument(
        exceptions=[
            BaselineException(
                fingerprint=finding_fingerprint(current),
                owner="finance-platform",
                reason="migration window",
                expires_on=date(2026, 9, 30),
            )
        ]
    )
    report = compare_baseline(
        baseline,
        [current],
        evaluation_date=date(2026, 9, 7),
        exceptions=exceptions,
    )
    assert report.items[0].accepted_by_exception is True
    assert report.status == "PASS"


def test_expired_exception_fails_closed() -> None:
    current = finding("new")
    baseline = capture_baseline("legacy", [])
    exceptions = BaselineExceptionDocument(
        exceptions=[
            BaselineException(
                fingerprint=finding_fingerprint(current),
                owner="finance-platform",
                reason="temporary acceptance",
                expires_on=date(2026, 9, 6),
            )
        ]
    )
    report = compare_baseline(
        baseline,
        [current],
        evaluation_date=date(2026, 9, 7),
        exceptions=exceptions,
    )
    assert report.expired_exception_count == 1
    assert report.items[0].accepted_by_exception is False
    assert report.status == "FAIL"


def test_canonical_report_is_deterministic() -> None:
    current = finding("new")
    baseline = capture_baseline("legacy", [])
    first = compare_baseline(baseline, [current], evaluation_date=date(2026, 9, 7))
    second = compare_baseline(baseline, [current], evaluation_date=date(2026, 9, 7))
    assert canonical_baseline_json(first) == canonical_baseline_json(second)
