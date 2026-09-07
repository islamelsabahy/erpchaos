from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from erpchaos.trace import TraceDiagnostics, TraceEvent, TransactionTrace, diagnose_trace

TRACE_DIVERGENCE_SCHEMA = "erpchaos.trace-divergence.v1"


class TraceDivergenceKind(StrEnum):
    exact = "EXACT"
    step_mismatch = "STEP_MISMATCH"
    missing_observed_step = "MISSING_OBSERVED_STEP"
    unexpected_observed_step = "UNEXPECTED_OBSERVED_STEP"


class TraceStepSnapshot(BaseModel):
    """Stable business-semantic snapshot for one trace step at the divergence frontier."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    source_system: str
    sequence: int


class TraceDivergenceReport(BaseModel):
    """Deterministic first-divergence report for two valid transaction traces."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.trace-divergence.v1"] = Field(
        default="erpchaos.trace-divergence.v1",
        alias="schema",
    )
    status: TraceDivergenceKind
    common_prefix_length: int = Field(ge=0)
    divergence_index: int | None = Field(default=None, ge=0)
    reason: str
    reference_trace_id: str
    observed_trace_id: str
    reference_transaction_id: str
    observed_transaction_id: str
    reference_step: TraceStepSnapshot | None = None
    observed_step: TraceStepSnapshot | None = None
    observed_causal_descendant_ids: list[str] = Field(default_factory=list)


class InvalidTraceComparisonError(ValueError):
    """Raised when either comparison input is not a valid deterministic trace."""

    def __init__(
        self,
        *,
        side: Literal["reference", "observed"],
        diagnostics: TraceDiagnostics,
    ) -> None:
        self.side = side
        self.diagnostics = diagnostics
        super().__init__(f"{side} transaction trace is invalid or causally ambiguous")


def _snapshot(event: TraceEvent) -> TraceStepSnapshot:
    return TraceStepSnapshot(
        event_id=event.event_id,
        event_type=event.event_type,
        source_system=event.source_system,
        sequence=event.sequence,
    )


def _step_signature(event: TraceEvent) -> tuple[str, str]:
    return (event.event_type, event.source_system)


def _ordered_events(trace: TransactionTrace, diagnostics: TraceDiagnostics) -> list[TraceEvent]:
    events_by_id = {event.event_id: event for event in trace.events}
    return [events_by_id[event_id] for event_id in diagnostics.ordered_event_ids]


def _causal_descendants(
    trace: TransactionTrace,
    diagnostics: TraceDiagnostics,
    root_event_id: str,
) -> list[str]:
    children: dict[str, set[str]] = {event.event_id: set() for event in trace.events}
    for event in trace.events:
        for reference in {event.parent_event_id, event.causation_event_id}:
            if reference is not None and reference in children:
                children[reference].add(event.event_id)

    reachable: set[str] = set()
    pending = sorted(children[root_event_id])
    while pending:
        current = pending.pop(0)
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(sorted(children[current]))
        pending.sort()

    return [
        event_id
        for event_id in diagnostics.ordered_event_ids
        if event_id in reachable
    ]


def compare_traces(
    reference: TransactionTrace,
    observed: TransactionTrace,
) -> TraceDivergenceReport:
    """Locate the first explicit semantic path divergence without fuzzy realignment."""

    reference_diagnostics = diagnose_trace(reference)
    if not reference_diagnostics.valid:
        raise InvalidTraceComparisonError(
            side="reference",
            diagnostics=reference_diagnostics,
        )

    observed_diagnostics = diagnose_trace(observed)
    if not observed_diagnostics.valid:
        raise InvalidTraceComparisonError(
            side="observed",
            diagnostics=observed_diagnostics,
        )

    reference_events = _ordered_events(reference, reference_diagnostics)
    observed_events = _ordered_events(observed, observed_diagnostics)
    common_prefix_length = 0

    for reference_event, observed_event in zip(reference_events, observed_events, strict=False):
        if _step_signature(reference_event) != _step_signature(observed_event):
            index = common_prefix_length
            return TraceDivergenceReport(
                status=TraceDivergenceKind.step_mismatch,
                common_prefix_length=common_prefix_length,
                divergence_index=index,
                reason=f"business step signature differs at index {index}",
                reference_trace_id=reference.trace_id,
                observed_trace_id=observed.trace_id,
                reference_transaction_id=reference.transaction_id,
                observed_transaction_id=observed.transaction_id,
                reference_step=_snapshot(reference_event),
                observed_step=_snapshot(observed_event),
                observed_causal_descendant_ids=_causal_descendants(
                    observed,
                    observed_diagnostics,
                    observed_event.event_id,
                ),
            )
        common_prefix_length += 1

    if len(reference_events) == len(observed_events):
        return TraceDivergenceReport(
            status=TraceDivergenceKind.exact,
            common_prefix_length=common_prefix_length,
            divergence_index=None,
            reason="business step signatures are identical",
            reference_trace_id=reference.trace_id,
            observed_trace_id=observed.trace_id,
            reference_transaction_id=reference.transaction_id,
            observed_transaction_id=observed.transaction_id,
        )

    if len(observed_events) < len(reference_events):
        index = len(observed_events)
        return TraceDivergenceReport(
            status=TraceDivergenceKind.missing_observed_step,
            common_prefix_length=common_prefix_length,
            divergence_index=index,
            reason=f"observed trace ends before reference step at index {index}",
            reference_trace_id=reference.trace_id,
            observed_trace_id=observed.trace_id,
            reference_transaction_id=reference.transaction_id,
            observed_transaction_id=observed.transaction_id,
            reference_step=_snapshot(reference_events[index]),
        )

    index = len(reference_events)
    observed_event = observed_events[index]
    return TraceDivergenceReport(
        status=TraceDivergenceKind.unexpected_observed_step,
        common_prefix_length=common_prefix_length,
        divergence_index=index,
        reason=f"observed trace contains an unexpected step at index {index}",
        reference_trace_id=reference.trace_id,
        observed_trace_id=observed.trace_id,
        reference_transaction_id=reference.transaction_id,
        observed_transaction_id=observed.transaction_id,
        observed_step=_snapshot(observed_event),
        observed_causal_descendant_ids=_causal_descendants(
            observed,
            observed_diagnostics,
            observed_event.event_id,
        ),
    )


def divergence_json(report: TraceDivergenceReport) -> str:
    """Render byte-stable UTF-8 JSON for CI, policy, and evidence pipelines."""

    payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
