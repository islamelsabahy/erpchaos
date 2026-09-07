from __future__ import annotations

import json

import pytest

from erpchaos.trace import (
    TraceProjectionError,
    TransactionTrace,
    diagnose_trace,
    diagnostics_json,
    project_trace,
)


def _trace() -> TransactionTrace:
    return TransactionTrace.model_validate(
        {
            "schema": "erpchaos.transaction-trace.v1",
            "trace_id": "trace-001",
            "transaction_id": "txn-001",
            "events": [
                {
                    "event_id": "reservation-001",
                    "event_type": "reservation.created",
                    "transaction_id": "txn-001",
                    "source_system": "crm",
                    "sequence": 10,
                    "payload": {"unit_ref": "UNIT-DEMO-203"},
                },
                {
                    "event_id": "finance-001",
                    "event_type": "finance.approved",
                    "transaction_id": "txn-001",
                    "source_system": "finance",
                    "sequence": 20,
                    "parent_event_id": "reservation-001",
                    "causation_event_id": "reservation-001",
                },
                {
                    "event_id": "payment-001",
                    "event_type": "payment.received",
                    "transaction_id": "txn-001",
                    "source_system": "accounting",
                    "sequence": 30,
                    "parent_event_id": "finance-001",
                    "causation_event_id": "finance-001",
                    "payload": {"amount_minor": 2500000, "currency": "EGP"},
                },
            ],
        }
    )


def test_valid_trace_reconstructs_deterministic_path() -> None:
    diagnostics = diagnose_trace(_trace())

    assert diagnostics.valid is True
    assert diagnostics.ordered_event_ids == [
        "reservation-001",
        "finance-001",
        "payment-001",
    ]
    assert diagnostics.source_systems == ["accounting", "crm", "finance"]
    assert diagnostics.issues == []


def test_unknown_canonical_trace_field_is_rejected() -> None:
    payload = _trace().model_dump(mode="json", by_alias=True)
    payload["unexpected"] = "must-fail-closed"

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        TransactionTrace.model_validate(payload)


def test_unknown_canonical_event_field_is_rejected() -> None:
    payload = _trace().model_dump(mode="json", by_alias=True)
    events = payload["events"]
    assert isinstance(events, list)
    first = events[0]
    assert isinstance(first, dict)
    first["unexpected"] = "must-fail-closed"

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        TransactionTrace.model_validate(payload)


def test_projection_preserves_business_event_semantics() -> None:
    stream = project_trace(_trace())

    assert stream.transaction_id == "txn-001"
    assert [event.event_id for event in stream.events] == [
        "reservation-001",
        "finance-001",
        "payment-001",
    ]
    assert [event.event_type for event in stream.events] == [
        "reservation.created",
        "finance.approved",
        "payment.received",
    ]
    assert stream.events[-1].payload == {"amount_minor": 2500000, "currency": "EGP"}


def test_missing_parent_is_reported_and_projection_refuses() -> None:
    trace = _trace().model_copy(deep=True)
    trace.events[-1].parent_event_id = "missing-parent"

    diagnostics = diagnose_trace(trace)

    assert diagnostics.valid is False
    assert diagnostics.ordered_event_ids == []
    assert [issue.code for issue in diagnostics.issues] == ["TRACE_MISSING_PARENT"]
    with pytest.raises(TraceProjectionError):
        project_trace(trace)


def test_duplicate_event_identity_is_rejected() -> None:
    trace = _trace().model_copy(deep=True)
    duplicate = trace.events[0].model_copy(deep=True)
    trace.events.append(duplicate)

    diagnostics = diagnose_trace(trace)

    assert diagnostics.valid is False
    assert "TRACE_DUPLICATE_EVENT_ID" in {issue.code for issue in diagnostics.issues}


def test_cross_transaction_contamination_is_rejected() -> None:
    trace = _trace().model_copy(deep=True)
    trace.events[-1].transaction_id = "txn-other"

    diagnostics = diagnose_trace(trace)

    assert diagnostics.valid is False
    assert [issue.code for issue in diagnostics.issues] == ["TRACE_CROSS_TRANSACTION"]


def test_causal_cycle_is_reported_without_inferred_order() -> None:
    trace = _trace().model_copy(deep=True)
    trace.events[0].parent_event_id = "payment-001"

    diagnostics = diagnose_trace(trace)

    assert diagnostics.valid is False
    assert diagnostics.ordered_event_ids == []
    assert {issue.code for issue in diagnostics.issues} == {"TRACE_CAUSAL_CYCLE"}
    assert {issue.event_id for issue in diagnostics.issues} == {
        "finance-001",
        "payment-001",
        "reservation-001",
    }


def test_diagnostics_json_is_byte_stable() -> None:
    diagnostics = diagnose_trace(_trace())

    first = diagnostics_json(diagnostics)
    second = diagnostics_json(diagnostics)

    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["schema"] == "erpchaos.trace-diagnostics.v1"
    assert payload["valid"] is True
    assert payload["ordered_event_ids"] == [
        "reservation-001",
        "finance-001",
        "payment-001",
    ]
