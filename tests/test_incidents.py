import pytest
from pydantic import ValidationError

from erpchaos.events import EventStream
from erpchaos.incidents import (
    IncidentSanitizationPolicy,
    sanitize_event_stream,
    validate_sanitized_event_stream,
)

_TEST_KEY = "test-only-pseudonym-key-12345"


def _stream() -> EventStream:
    return EventStream.model_validate(
        {
            "transaction_id": "INCIDENT-SALE-001",
            "events": [
                {
                    "event_id": "event-001",
                    "event_type": "reservation.requested",
                    "payload": {
                        "customer_email": "alice@example.test",
                        "customer_phone": "+20 100 000 0000",
                        "unit_ref": "UNIT-A-203",
                        "state": "reserved",
                        "access_token": "synthetic-secret-value",
                        "internal_note": "drop by default",
                        "source": {
                            "operator_email": "operator@example.test",
                            "system": "odoo",
                        },
                    },
                },
                {
                    "event_id": "event-002",
                    "event_type": "payment.received",
                    "payload": {
                        "customer_email": "alice@example.test",
                        "unit_ref": "UNIT-A-203",
                        "state": "paid",
                        "amount": 125000,
                    },
                },
            ],
        }
    )


def _policy() -> IncidentSanitizationPolicy:
    return IncidentSanitizationPolicy.model_validate(
        {
            "schema": "erpchaos.incident-sanitization-policy.v1",
            "name": "Synthetic property-sale incident",
            "default_action": "drop",
            "pii_detection": True,
            "rules": [
                {"path": "customer_email", "action": "tokenize"},
                {"path": "customer_phone", "action": "redact"},
                {"path": "unit_ref", "action": "tokenize"},
                {"path": "state", "action": "keep"},
                {"path": "amount", "action": "drop"},
                {"path": "source.operator_email", "action": "tokenize"},
                {"path": "source.system", "action": "keep"},
            ],
        }
    )


def test_sanitization_preserves_order_and_correlation_without_raw_pii() -> None:
    original = _stream()
    result = sanitize_event_stream(original, _policy(), _TEST_KEY)
    sanitized = result.stream

    assert sanitized.transaction_id.startswith("incident-transaction-")
    assert [event.event_type for event in sanitized.events] == [
        "reservation.requested",
        "payment.received",
    ]
    assert all(event.event_id.startswith("incident-event-") for event in sanitized.events)

    first = sanitized.events[0].payload
    second = sanitized.events[1].payload
    assert first["customer_email"] == second["customer_email"]
    assert first["customer_email"].startswith("token-field-")
    assert first["customer_phone"] == "[REDACTED]"
    assert first["unit_ref"] == second["unit_ref"]
    assert first["unit_ref"].startswith("token-field-")
    assert first["state"] == "reserved"
    assert second["state"] == "paid"
    assert first["source"]["operator_email"].startswith("token-field-")
    assert first["source"]["system"] == "odoo"

    serialized = sanitized.model_dump_json()
    assert "alice@example.test" not in serialized
    assert "+20 100 000 0000" not in serialized
    assert "synthetic-secret-value" not in serialized
    assert "internal_note" not in serialized
    assert "125000" not in serialized


def test_sanitization_is_stable_for_same_key() -> None:
    first = sanitize_event_stream(_stream(), _policy(), _TEST_KEY).stream
    second = sanitize_event_stream(_stream(), _policy(), _TEST_KEY).stream

    assert first == second


def test_different_key_changes_pseudonyms() -> None:
    first = sanitize_event_stream(_stream(), _policy(), _TEST_KEY).stream
    second = sanitize_event_stream(
        _stream(),
        _policy(),
        "different-test-key-987654321",
    ).stream

    assert first.transaction_id != second.transaction_id
    assert first.events[0].payload["customer_email"] != second.events[0].payload["customer_email"]


def test_policy_rejects_non_drop_rule_for_secret_field() -> None:
    payload = _policy().model_dump(mode="json")
    payload["rules"].append({"path": "api_key", "action": "tokenize"})

    with pytest.raises(ValidationError, match="may only use the drop action"):
        IncidentSanitizationPolicy.model_validate(payload)


def test_keep_action_fails_closed_on_detected_pii() -> None:
    payload = _policy().model_dump(mode="json")
    for rule in payload["rules"]:
        if rule["path"] == "customer_email":
            rule["action"] = "keep"
    policy = IncidentSanitizationPolicy.model_validate(payload)

    with pytest.raises(ValueError, match="keep action would expose detected PII"):
        sanitize_event_stream(_stream(), policy, _TEST_KEY)


def test_keep_action_rejects_collection_values() -> None:
    stream = _stream()
    stream.events[0].payload["watchers"] = ["observer@example.test"]
    payload = _policy().model_dump(mode="json")
    payload["rules"].append({"path": "watchers", "action": "keep"})
    policy = IncidentSanitizationPolicy.model_validate(payload)

    with pytest.raises(ValueError, match="only allowed for scalar fields"):
        sanitize_event_stream(stream, policy, _TEST_KEY)


def test_validator_rejects_raw_pii_leak() -> None:
    sanitized = sanitize_event_stream(_stream(), _policy(), _TEST_KEY).stream
    sanitized.events[0].payload["customer_email"] = "leak@example.test"

    with pytest.raises(ValueError, match="raw PII"):
        validate_sanitized_event_stream(sanitized)


def test_validator_rejects_secret_field_leak() -> None:
    sanitized = sanitize_event_stream(_stream(), _policy(), _TEST_KEY).stream
    sanitized.events[0].payload["password"] = "should-never-exist"

    with pytest.raises(ValueError, match="credential field"):
        validate_sanitized_event_stream(sanitized)


def test_short_pseudonym_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 16 characters"):
        sanitize_event_stream(_stream(), _policy(), "too-short")
