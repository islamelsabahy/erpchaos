from __future__ import annotations

import json
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from erpchaos.events import BusinessEvent, EventStream

TRACE_SCHEMA = "erpchaos.transaction-trace.v1"
TRACE_DIAGNOSTICS_SCHEMA = "erpchaos.trace-diagnostics.v1"


class TraceEvent(BaseModel):
    """One sanitized vendor-neutral event in a correlated business transaction trace."""

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    parent_event_id: str | None = None
    causation_event_id: str | None = None
    timestamp: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TransactionTrace(BaseModel):
    """Canonical offline transaction-trace document."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["erpchaos.transaction-trace.v1"] = Field(
        default=TRACE_SCHEMA,
        alias="schema",
    )
    trace_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    events: list[TraceEvent] = Field(min_length=1)


class TraceIssue(BaseModel):
    """One stable deterministic trace-correlation diagnostic."""

    issue_id: str
    code: str
    severity: Literal["ERROR"] = "ERROR"
    message: str
    event_id: str | None = None
    related_event_id: str | None = None


class TraceDiagnostics(BaseModel):
    """Deterministic validation and ordering result for a transaction trace."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["erpchaos.trace-diagnostics.v1"] = Field(
        default=TRACE_DIAGNOSTICS_SCHEMA,
        alias="schema",
    )
    trace_id: str
    transaction_id: str
    valid: bool
    source_systems: list[str]
    ordered_event_ids: list[str]
    issues: list[TraceIssue]


class TraceProjectionError(ValueError):
    """Raised when an invalid or ambiguous trace cannot be projected safely."""

    def __init__(self, diagnostics: TraceDiagnostics) -> None:
        self.diagnostics = diagnostics
        super().__init__("transaction trace is invalid or causally ambiguous")


def _issue(
    code: str,
    message: str,
    *,
    event_id: str | None = None,
    related_event_id: str | None = None,
) -> TraceIssue:
    subject = event_id or "trace"
    relation = related_event_id or "-"
    return TraceIssue(
        issue_id=f"{code}:{subject}:{relation}",
        code=code,
        message=message,
        event_id=event_id,
        related_event_id=related_event_id,
    )


def _issue_sort_key(issue: TraceIssue) -> tuple[str, str, str, str]:
    return (
        issue.code,
        issue.event_id or "",
        issue.related_event_id or "",
        issue.issue_id,
    )


def _event_sort_key(event: TraceEvent) -> tuple[int, str]:
    return (event.sequence, event.event_id)


def _topological_order(events_by_id: dict[str, TraceEvent]) -> tuple[list[str], list[TraceIssue]]:
    indegree = {event_id: 0 for event_id in events_by_id}
    children: dict[str, set[str]] = {event_id: set() for event_id in events_by_id}

    for event in events_by_id.values():
        references = {
            reference
            for reference in (event.parent_event_id, event.causation_event_id)
            if reference is not None
        }
        for reference in references:
            if event.event_id not in children[reference]:
                children[reference].add(event.event_id)
                indegree[event.event_id] += 1

    ready = sorted(
        (events_by_id[event_id] for event_id, degree in indegree.items() if degree == 0),
        key=_event_sort_key,
    )
    ordered: list[str] = []

    while ready:
        current = ready.pop(0)
        ordered.append(current.event_id)
        for child_id in sorted(children[current.event_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(events_by_id[child_id])
                ready.sort(key=_event_sort_key)

    if len(ordered) == len(events_by_id):
        return ordered, []

    cyclic_ids = sorted(event_id for event_id, degree in indegree.items() if degree > 0)
    issues = [
        _issue(
            "TRACE_CAUSAL_CYCLE",
            "event participates in a parent/causation cycle",
            event_id=event_id,
        )
        for event_id in cyclic_ids
    ]
    return [], issues


def diagnose_trace(trace: TransactionTrace) -> TraceDiagnostics:
    """Validate identity/correlation and reconstruct a deterministic causal order."""

    issues: list[TraceIssue] = []
    id_counts = Counter(event.event_id for event in trace.events)
    duplicate_ids = {event_id for event_id, count in id_counts.items() if count > 1}

    for event_id in sorted(duplicate_ids):
        issues.append(
            _issue(
                "TRACE_DUPLICATE_EVENT_ID",
                "event identity occurs more than once in the trace",
                event_id=event_id,
            )
        )

    known_ids = set(id_counts)
    for event in sorted(trace.events, key=_event_sort_key):
        if event.transaction_id != trace.transaction_id:
            issues.append(
                _issue(
                    "TRACE_CROSS_TRANSACTION",
                    "event transaction_id does not match the trace transaction_id",
                    event_id=event.event_id,
                )
            )

        if event.parent_event_id is not None:
            if event.parent_event_id not in known_ids:
                issues.append(
                    _issue(
                        "TRACE_MISSING_PARENT",
                        "parent_event_id does not resolve inside the trace",
                        event_id=event.event_id,
                        related_event_id=event.parent_event_id,
                    )
                )
            elif event.parent_event_id in duplicate_ids:
                issues.append(
                    _issue(
                        "TRACE_AMBIGUOUS_PARENT",
                        "parent_event_id resolves to a duplicated event identity",
                        event_id=event.event_id,
                        related_event_id=event.parent_event_id,
                    )
                )

        if event.causation_event_id is not None:
            if event.causation_event_id not in known_ids:
                issues.append(
                    _issue(
                        "TRACE_MISSING_CAUSATION",
                        "causation_event_id does not resolve inside the trace",
                        event_id=event.event_id,
                        related_event_id=event.causation_event_id,
                    )
                )
            elif event.causation_event_id in duplicate_ids:
                issues.append(
                    _issue(
                        "TRACE_AMBIGUOUS_CAUSATION",
                        "causation_event_id resolves to a duplicated event identity",
                        event_id=event.event_id,
                        related_event_id=event.causation_event_id,
                    )
                )

    ordered_event_ids: list[str] = []
    if not issues:
        events_by_id = {event.event_id: event for event in trace.events}
        ordered_event_ids, cycle_issues = _topological_order(events_by_id)
        issues.extend(cycle_issues)

    issues.sort(key=_issue_sort_key)
    valid = not issues
    if not valid:
        ordered_event_ids = []

    return TraceDiagnostics(
        trace_id=trace.trace_id,
        transaction_id=trace.transaction_id,
        valid=valid,
        source_systems=sorted({event.source_system for event in trace.events}),
        ordered_event_ids=ordered_event_ids,
        issues=issues,
    )


def project_trace(trace: TransactionTrace) -> EventStream:
    """Project a valid transaction trace into the ERPChaos replay EventStream model."""

    diagnostics = diagnose_trace(trace)
    if not diagnostics.valid:
        raise TraceProjectionError(diagnostics)

    events_by_id = {event.event_id: event for event in trace.events}
    return EventStream(
        transaction_id=trace.transaction_id,
        events=[
            BusinessEvent(
                event_id=event_id,
                event_type=events_by_id[event_id].event_type,
                payload=events_by_id[event_id].payload,
            )
            for event_id in diagnostics.ordered_event_ids
        ],
    )


def diagnostics_json(diagnostics: TraceDiagnostics) -> str:
    """Render byte-stable UTF-8 JSON for CI and evidence pipelines."""

    payload = diagnostics.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
