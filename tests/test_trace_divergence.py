from __future__ import annotations

import json

import pytest

from erpchaos.trace import TransactionTrace
from erpchaos.trace_divergence import (
    InvalidTraceComparisonError,
    TraceDivergenceKind,
    compare_traces,
    divergence_json,
)


def _trace(*, trace_id: str, event_prefix: str) -> TransactionTrace:
    reservation_id = f"{event_prefix}-reservation"
    finance_id = f"{event_prefix}-finance"
    payment_id = f"{event_prefix}-payment"
    contract_id = f"{event_prefix}-contract"
    sold_id = f"{event_prefix}-sold"
    return TransactionTrace.model_validate(
        {
            "schema": "erpchaos.transaction-trace.v1",
            "trace_id": trace_id,
            "transaction_id": f"transaction-{event_prefix}",
            "events": [
                {
                    "event_id": reservation_id,
                    "event_type": "reservation.created",
                    "transaction_id": f"transaction-{event_prefix}",
                    "source_system": "crm",
                    "sequence": 10,
                },
                {
                    "event_id": finance_id,
                    "event_type": "finance.approved",
                    "transaction_id": f"transaction-{event_prefix}",
                    "source_system": "finance",
                    "sequence": 20,
                    "parent_event_id": reservation_id,
                    "causation_event_id": reservation_id,
                },
                {
                    "event_id": payment_id,
                    "event_type": "payment.received",
                    "transaction_id": f"transaction-{event_prefix}",
                    "source_system": "accounting",
                    "sequence": 30,
                    "parent_event_id": finance_id,
                    "causation_event_id": finance_id,
                },
                {
                    "event_id": contract_id,
                    "event_type": "contract.signed",
                    "transaction_id": f"transaction-{event_prefix}",
                    "source_system": "erp",
                    "sequence": 40,
                    "parent_event_id": payment_id,
                    "causation_event_id": payment_id,
                },
                {
                    "event_id": sold_id,
                    "event_type": "unit.sold",
                    "transaction_id": f"transaction-{event_prefix}",
                    "source_system": "erp",
                    "sequence": 50,
                    "parent_event_id": contract_id,
                    "causation_event_id": contract_id,
                },
            ],
        }
    )


def test_semantically_identical_paths_are_exact_even_when_event_ids_differ() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")

    report = compare_traces(reference, observed)

    assert report.status is TraceDivergenceKind.exact
    assert report.common_prefix_length == 5
    assert report.divergence_index is None
    assert report.reference_step is None
    assert report.observed_step is None
    assert report.observed_causal_descendant_ids == []


def test_step_mismatch_localizes_first_divergence_and_descendants() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")
    observed.events[2].event_type = "payment.rejected"

    report = compare_traces(reference, observed)

    assert report.status is TraceDivergenceKind.step_mismatch
    assert report.common_prefix_length == 2
    assert report.divergence_index == 2
    assert report.reference_step is not None
    assert report.reference_step.event_type == "payment.received"
    assert report.observed_step is not None
    assert report.observed_step.event_type == "payment.rejected"
    assert report.observed_causal_descendant_ids == [
        "observed-contract",
        "observed-sold",
    ]


def test_shorter_observed_path_reports_missing_step() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")
    observed.events = observed.events[:3]

    report = compare_traces(reference, observed)

    assert report.status is TraceDivergenceKind.missing_observed_step
    assert report.common_prefix_length == 3
    assert report.divergence_index == 3
    assert report.reference_step is not None
    assert report.reference_step.event_type == "contract.signed"
    assert report.observed_step is None
    assert report.observed_causal_descendant_ids == []


def test_extra_observed_path_reports_unexpected_step_and_descendants() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    reference.events = reference.events[:3]
    observed = _trace(trace_id="observed-trace", event_prefix="observed")

    report = compare_traces(reference, observed)

    assert report.status is TraceDivergenceKind.unexpected_observed_step
    assert report.common_prefix_length == 3
    assert report.divergence_index == 3
    assert report.reference_step is None
    assert report.observed_step is not None
    assert report.observed_step.event_type == "contract.signed"
    assert report.observed_causal_descendant_ids == ["observed-sold"]


def test_invalid_reference_trace_fails_closed() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")
    reference.events[-1].parent_event_id = "missing-parent"

    with pytest.raises(InvalidTraceComparisonError) as caught:
        compare_traces(reference, observed)

    assert caught.value.side == "reference"
    assert caught.value.diagnostics.valid is False


def test_invalid_observed_trace_fails_closed() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")
    observed.events[-1].causation_event_id = "missing-causation"

    with pytest.raises(InvalidTraceComparisonError) as caught:
        compare_traces(reference, observed)

    assert caught.value.side == "observed"
    assert caught.value.diagnostics.valid is False


def test_divergence_json_is_byte_stable() -> None:
    reference = _trace(trace_id="reference-trace", event_prefix="reference")
    observed = _trace(trace_id="observed-trace", event_prefix="observed")
    observed.events[2].event_type = "payment.rejected"

    report = compare_traces(reference, observed)
    first = divergence_json(report)
    second = divergence_json(report)

    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["schema"] == "erpchaos.trace-divergence.v1"
    assert payload["status"] == "STEP_MISMATCH"
    assert payload["divergence_index"] == 2
    assert payload["observed_causal_descendant_ids"] == [
        "observed-contract",
        "observed-sold",
    ]
