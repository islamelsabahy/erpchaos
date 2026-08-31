import pytest
from pydantic import ValidationError

from erpchaos.adapters.odoo import (
    OdooExportAdapter,
    OdooExportFixture,
    export_event_stream_document,
)


def _fixture() -> dict[str, object]:
    return {
        "config": {
            "environment": "staging",
            "base_url": "https://odoo-staging.example.test",
            "database": "erpchaos_demo",
            "read_only": True,
        },
        "mappings": [
            {
                "model": "sale.order",
                "operation": "reserve",
                "event_type": "reservation.requested",
                "transaction_field": "transaction_ref",
                "payload_fields": ["unit_ref", "state"],
            }
        ],
        "activities": [
            {
                "activity_id": "activity-001",
                "model": "sale.order",
                "operation": "reserve",
                "values": {
                    "transaction_ref": "DEMO-SALE-001",
                    "unit_ref": "UNIT-A-203",
                    "state": "reserved",
                    "internal_note": "must not be exported",
                },
            }
        ],
    }


def test_adapter_translates_to_vendor_neutral_event_stream() -> None:
    fixture = OdooExportFixture.model_validate(_fixture())
    streams = OdooExportAdapter(fixture).translate()

    assert len(streams) == 1
    stream = streams[0]
    assert stream.transaction_id.startswith("odoo-transaction-")
    assert "DEMO-SALE-001" not in stream.transaction_id
    assert len(stream.events) == 1

    event = stream.events[0]
    assert event.event_id.startswith("odoo-event-")
    assert event.event_type == "reservation.requested"
    assert event.payload["unit_ref"] == "UNIT-A-203"
    assert event.payload["state"] == "reserved"
    assert "internal_note" not in event.payload
    assert event.payload["source"]["system"] == "odoo"

    exported = export_event_stream_document(streams)
    assert exported["schema"] == "erpchaos.event-stream-export.v1"
    assert exported["streams"][0]["transaction_id"] == stream.transaction_id


def test_adapter_rejects_write_mode() -> None:
    payload = _fixture()
    payload["config"]["read_only"] = False

    with pytest.raises(ValidationError):
        OdooExportFixture.model_validate(payload)


def test_adapter_rejects_credentials_in_config() -> None:
    payload = _fixture()
    payload["config"]["password"] = "do-not-store-this"

    with pytest.raises(ValidationError):
        OdooExportFixture.model_validate(payload)


def test_adapter_rejects_credentials_embedded_in_url() -> None:
    payload = _fixture()
    payload["config"]["base_url"] = "https://user:password@odoo-staging.example.test"

    with pytest.raises(ValidationError, match="credentials must not be embedded"):
        OdooExportFixture.model_validate(payload)


def test_adapter_rejects_sensitive_mapping_fields() -> None:
    payload = _fixture()
    payload["mappings"][0]["payload_fields"] = ["unit_ref", "access_token"]

    with pytest.raises(ValidationError, match="sensitive fields are not allowed"):
        OdooExportFixture.model_validate(payload)


def test_adapter_fails_closed_on_unmapped_activity() -> None:
    payload = _fixture()
    payload["activities"][0]["operation"] = "unexpected_operation"
    fixture = OdooExportFixture.model_validate(payload)

    with pytest.raises(ValueError, match="unmapped Odoo activity"):
        OdooExportAdapter(fixture).translate()
