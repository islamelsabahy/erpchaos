from __future__ import annotations

from typing import Any

from erpchaos.trace import TraceEvent, TransactionTrace

_TRANSACTION_ATTRIBUTE = "erpchaos.transaction_id"
_EVENT_TYPE_ATTRIBUTE = "erpchaos.event_type"
_SEQUENCE_ATTRIBUTE = "erpchaos.sequence"
_CAUSATION_ATTRIBUTE = "erpchaos.causation_span_id"
_PAYLOAD_PREFIX = "erpchaos.payload."
_SERVICE_NAME_ATTRIBUTE = "service.name"


def translate_otlp_json(document: dict[str, Any]) -> TransactionTrace:
    """Translate one sanitized offline OTLP JSON export into a canonical transaction trace."""

    translated_events: list[TraceEvent] = []
    trace_ids: set[str] = set()
    transaction_ids: set[str] = set()

    resource_spans = document.get("resourceSpans")
    if not isinstance(resource_spans, list) or not resource_spans:
        raise ValueError("OTLP export must contain a non-empty resourceSpans list")

    for resource_span in resource_spans:
        if not isinstance(resource_span, dict):
            raise ValueError("OTLP resourceSpans entries must be objects")
        source_system = _source_system(resource_span)
        scope_spans = resource_span.get("scopeSpans")
        if not isinstance(scope_spans, list) or not scope_spans:
            raise ValueError("OTLP resourceSpans entry must contain non-empty scopeSpans")

        for scope_span in scope_spans:
            if not isinstance(scope_span, dict):
                raise ValueError("OTLP scopeSpans entries must be objects")
            spans = scope_span.get("spans")
            if not isinstance(spans, list) or not spans:
                raise ValueError("OTLP scopeSpans entry must contain non-empty spans")

            for span in spans:
                if not isinstance(span, dict):
                    raise ValueError("OTLP spans entries must be objects")
                event = _translate_span(span, source_system=source_system)
                trace_id = _required_string(span, "traceId", context="OTLP span")
                trace_ids.add(trace_id)
                transaction_ids.add(event.transaction_id)
                translated_events.append(event)

    if len(trace_ids) != 1:
        raise ValueError("OTLP export must contain exactly one traceId")
    if len(transaction_ids) != 1:
        raise ValueError("OTLP export must contain exactly one ERPChaos transaction_id")

    return TransactionTrace(
        trace_id=next(iter(trace_ids)),
        transaction_id=next(iter(transaction_ids)),
        events=translated_events,
    )


def _translate_span(span: dict[str, Any], *, source_system: str) -> TraceEvent:
    attributes = _attributes(span.get("attributes"), context="OTLP span attributes")
    transaction_id = _required_attribute_string(attributes, _TRANSACTION_ATTRIBUTE)
    event_type = _required_attribute_string(attributes, _EVENT_TYPE_ATTRIBUTE)
    sequence = _required_attribute_int(attributes, _SEQUENCE_ATTRIBUTE)
    span_id = _required_string(span, "spanId", context="OTLP span")

    parent_span_id = span.get("parentSpanId")
    if parent_span_id in (None, ""):
        parent_event_id = None
    elif isinstance(parent_span_id, str):
        parent_event_id = parent_span_id
    else:
        raise ValueError("OTLP parentSpanId must be a string when present")

    causation = attributes.get(_CAUSATION_ATTRIBUTE)
    if causation is None:
        causation_event_id = None
    elif isinstance(causation, str) and causation:
        causation_event_id = causation
    else:
        raise ValueError(f"{_CAUSATION_ATTRIBUTE} must be a non-empty string when present")

    payload = {
        key.removeprefix(_PAYLOAD_PREFIX): value
        for key, value in sorted(attributes.items())
        if key.startswith(_PAYLOAD_PREFIX)
    }

    timestamp_value = span.get("startTimeUnixNano")
    if timestamp_value is None:
        timestamp = None
    elif isinstance(timestamp_value, (str, int)) and not isinstance(timestamp_value, bool):
        timestamp = str(timestamp_value)
    else:
        raise ValueError("OTLP startTimeUnixNano must be a string or integer when present")

    return TraceEvent(
        event_id=span_id,
        event_type=event_type,
        transaction_id=transaction_id,
        source_system=source_system,
        sequence=sequence,
        parent_event_id=parent_event_id,
        causation_event_id=causation_event_id,
        timestamp=timestamp,
        payload=payload,
    )


def _source_system(resource_span: dict[str, Any]) -> str:
    resource = resource_span.get("resource")
    if not isinstance(resource, dict):
        raise ValueError("OTLP resourceSpans entry must contain a resource object")
    attributes = _attributes(resource.get("attributes"), context="OTLP resource attributes")
    return _required_attribute_string(attributes, _SERVICE_NAME_ATTRIBUTE)


def _attributes(raw: Any, *, context: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ValueError(f"{context} must be a list")

    result: dict[str, Any] = {}
    for attribute in raw:
        if not isinstance(attribute, dict):
            raise ValueError(f"{context} entries must be objects")
        key = _required_string(attribute, "key", context=context)
        if key in result:
            raise ValueError(f"duplicate OTLP attribute key: {key}")
        result[key] = _decode_any_value(attribute.get("value"), key=key)
    return result


def _decode_any_value(raw: Any, *, key: str) -> Any:
    if not isinstance(raw, dict):
        raise ValueError(f"OTLP attribute {key!r} must contain a value object")

    supported = [
        field
        for field in ("stringValue", "intValue", "boolValue", "doubleValue")
        if field in raw
    ]
    if len(supported) != 1:
        raise ValueError(
            f"OTLP attribute {key!r} must use exactly one supported scalar value type"
        )

    field = supported[0]
    value = raw[field]
    if field == "stringValue":
        if not isinstance(value, str):
            raise ValueError(f"OTLP attribute {key!r} stringValue must be a string")
        return value
    if field == "intValue":
        if isinstance(value, bool):
            raise ValueError(f"OTLP attribute {key!r} intValue must be an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(
                    f"OTLP attribute {key!r} intValue must contain an integer"
                ) from exc
        raise ValueError(f"OTLP attribute {key!r} intValue must be an integer or string")
    if field == "boolValue":
        if not isinstance(value, bool):
            raise ValueError(f"OTLP attribute {key!r} boolValue must be boolean")
        return value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"OTLP attribute {key!r} doubleValue must be numeric")
    return float(value)


def _required_string(payload: dict[str, Any], key: str, *, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} requires non-empty string field {key!r}")
    return value


def _required_attribute_string(attributes: dict[str, Any], key: str) -> str:
    value = attributes.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"required OTLP attribute {key!r} must be a non-empty string")
    return value


def _required_attribute_int(attributes: dict[str, Any], key: str) -> int:
    value = attributes.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"required OTLP attribute {key!r} must be an integer")
    if value < 0:
        raise ValueError(f"required OTLP attribute {key!r} must be non-negative")
    return value
