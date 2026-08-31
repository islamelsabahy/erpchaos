from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from erpchaos.events import BusinessEvent, EventStream


class AdapterEnvironment(StrEnum):
    demo = "demo"
    test = "test"
    staging = "staging"


class OdooAdapterConfig(BaseModel):
    """Connection metadata only. Credentials are intentionally unsupported."""

    model_config = ConfigDict(extra="forbid")

    environment: AdapterEnvironment
    base_url: HttpUrl
    database: str = Field(min_length=1)
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_safe_url(self) -> OdooAdapterConfig:
        parsed = urlsplit(str(self.base_url))
        if parsed.username or parsed.password:
            raise ValueError("credentials must not be embedded in the adapter URL")
        if parsed.query or parsed.fragment:
            raise ValueError("adapter URL must not contain query strings or fragments")
        return self


class OdooEventMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    transaction_field: str = Field(min_length=1)
    payload_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_safe_fields(self) -> OdooEventMapping:
        fields = [self.transaction_field, *self.payload_fields]
        unsafe = [field for field in fields if _is_sensitive_field(field)]
        if unsafe:
            names = ", ".join(sorted(set(unsafe)))
            raise ValueError(f"sensitive fields are not allowed in adapter mappings: {names}")
        return self


class OdooActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)


class OdooExportFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: OdooAdapterConfig
    mappings: list[OdooEventMapping] = Field(min_length=1)
    activities: list[OdooActivity] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_mappings(self) -> OdooExportFixture:
        keys = [(mapping.model, mapping.operation) for mapping in self.mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("Odoo model/operation mappings must be unique")
        return self


@dataclass(frozen=True)
class OdooExportAdapter:
    """Translate previously exported Odoo activity without contacting Odoo."""

    fixture: OdooExportFixture

    def translate(self) -> list[EventStream]:
        mappings = {
            (mapping.model, mapping.operation): mapping
            for mapping in self.fixture.mappings
        }
        transaction_order: list[str] = []
        events_by_transaction: dict[str, list[BusinessEvent]] = {}

        for activity in self.fixture.activities:
            key = (activity.model, activity.operation)
            mapping = mappings.get(key)
            if mapping is None:
                raise ValueError(
                    "unmapped Odoo activity: "
                    f"model={activity.model}, operation={activity.operation}"
                )

            transaction_value = activity.values.get(mapping.transaction_field)
            if not isinstance(transaction_value, (str, int)) or isinstance(
                transaction_value,
                bool,
            ):
                raise ValueError(
                    f"transaction field {mapping.transaction_field!r} must be a string or integer"
                )

            missing_fields = [
                field
                for field in mapping.payload_fields
                if field not in activity.values
            ]
            if missing_fields:
                names = ", ".join(missing_fields)
                raise ValueError(f"mapped payload field(s) missing from activity: {names}")

            transaction_id = _safe_identifier("transaction", transaction_value)
            if transaction_id not in events_by_transaction:
                transaction_order.append(transaction_id)
                events_by_transaction[transaction_id] = []

            payload = {
                field: activity.values[field]
                for field in mapping.payload_fields
            }
            payload["source"] = {
                "system": "odoo",
                "environment": self.fixture.config.environment.value,
                "model": activity.model,
                "operation": activity.operation,
            }

            events_by_transaction[transaction_id].append(
                BusinessEvent(
                    event_id=_safe_identifier("event", activity.activity_id),
                    event_type=mapping.event_type,
                    payload=payload,
                )
            )

        return [
            EventStream(
                transaction_id=transaction_id,
                events=events_by_transaction[transaction_id],
            )
            for transaction_id in transaction_order
        ]


def export_event_stream_document(streams: list[EventStream]) -> dict[str, Any]:
    """Return a credential-free, schema-valid document suitable for YAML export."""

    return {
        "schema": "erpchaos.event-stream-export.v1",
        "streams": [stream.model_dump(mode="json") for stream in streams],
    }


def _safe_identifier(namespace: str, value: str | int) -> str:
    digest = sha256(f"{namespace}:{value}".encode()).hexdigest()[:16]
    return f"odoo-{namespace}-{digest}"


def _is_sensitive_field(field: str) -> bool:
    normalized = field.lower().replace("-", "_")
    sensitive_tokens = (
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "session_id",
    )
    return any(token in normalized for token in sensitive_tokens)
