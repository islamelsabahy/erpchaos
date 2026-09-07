from __future__ import annotations

import json
from pathlib import Path

import pytest

from erpchaos.adapters.opentelemetry import translate_otlp_json
from erpchaos.trace import diagnose_trace

_FIXTURE = Path("examples/traces/property-sale.otel.json")


def _fixture() -> dict[str, object]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_offline_otlp_export_translates_to_valid_transaction_trace() -> None:
    trace = translate_otlp_json(_fixture())
    diagnostics = diagnose_trace(trace)

    assert trace.schema_version == "erpchaos.transaction-trace.v1"
    assert trace.trace_id == "otel-trace-demo-001"
    assert trace.transaction_id == "property-sale-otel-001"
    assert diagnostics.valid is True
    assert diagnostics.ordered_event_ids == [
        "span-reservation-001",
        "span-finance-001",
        "span-payment-001",
    ]
    assert trace.events[-1].payload == {"amount_minor": 2500000, "currency": "EGP"}
    assert "authorization" not in json.dumps(trace.model_dump(mode="json"))


def test_multiple_otlp_trace_ids_fail_closed() -> None:
    document = _fixture()
    resource_spans = document["resourceSpans"]
    assert isinstance(resource_spans, list)
    third_resource = resource_spans[-1]
    assert isinstance(third_resource, dict)
    scope_spans = third_resource["scopeSpans"]
    assert isinstance(scope_spans, list)
    scope = scope_spans[0]
    assert isinstance(scope, dict)
    spans = scope["spans"]
    assert isinstance(spans, list)
    span = spans[0]
    assert isinstance(span, dict)
    span["traceId"] = "another-trace"

    with pytest.raises(ValueError, match="exactly one traceId"):
        translate_otlp_json(document)


def test_missing_explicit_business_sequence_fails_closed() -> None:
    document = _fixture()
    resource_spans = document["resourceSpans"]
    assert isinstance(resource_spans, list)
    first_resource = resource_spans[0]
    assert isinstance(first_resource, dict)
    scope_spans = first_resource["scopeSpans"]
    assert isinstance(scope_spans, list)
    scope = scope_spans[0]
    assert isinstance(scope, dict)
    spans = scope["spans"]
    assert isinstance(spans, list)
    span = spans[0]
    assert isinstance(span, dict)
    attributes = span["attributes"]
    assert isinstance(attributes, list)
    span["attributes"] = [
        attribute
        for attribute in attributes
        if isinstance(attribute, dict) and attribute.get("key") != "erpchaos.sequence"
    ]

    with pytest.raises(ValueError, match="erpchaos.sequence"):
        translate_otlp_json(document)


def test_multiple_business_transaction_ids_fail_closed() -> None:
    document = _fixture()
    resource_spans = document["resourceSpans"]
    assert isinstance(resource_spans, list)
    third_resource = resource_spans[-1]
    assert isinstance(third_resource, dict)
    scope_spans = third_resource["scopeSpans"]
    assert isinstance(scope_spans, list)
    scope = scope_spans[0]
    assert isinstance(scope, dict)
    spans = scope["spans"]
    assert isinstance(spans, list)
    span = spans[0]
    assert isinstance(span, dict)
    attributes = span["attributes"]
    assert isinstance(attributes, list)
    for attribute in attributes:
        if isinstance(attribute, dict) and attribute.get("key") == "erpchaos.transaction_id":
            value = attribute["value"]
            assert isinstance(value, dict)
            value["stringValue"] = "another-transaction"

    with pytest.raises(ValueError, match="exactly one ERPChaos transaction_id"):
        translate_otlp_json(document)
