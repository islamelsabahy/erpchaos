from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erpchaos.events import BusinessEvent, EventStream

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{7,}[0-9]$")
_REDACTED = "[REDACTED]"
_DROP = object()

_SECRET_TOKENS = (
    "password",
    "passwd",
    "secret",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "credential",
    "session_id",
    "authorization",
    "cookie",
)
_PII_TOKENS = (
    "email",
    "phone",
    "mobile",
    "customer_name",
    "first_name",
    "last_name",
    "full_name",
    "address",
    "national_id",
    "passport",
)


class SanitizationAction(StrEnum):
    keep = "keep"
    tokenize = "tokenize"
    redact = "redact"
    drop = "drop"


class IncidentFieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    action: SanitizationAction

    @model_validator(mode="after")
    def reject_secret_keep_rules(self) -> IncidentFieldRule:
        if _is_secret_path(self.path) and self.action is not SanitizationAction.drop:
            raise ValueError("credential and secret fields may only use the drop action")
        return self


class IncidentSanitizationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.incident-sanitization-policy.v1"] = Field(alias="schema")
    name: str = Field(min_length=1)
    default_action: Literal["drop"] = "drop"
    pii_detection: bool = True
    rules: list[IncidentFieldRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_rule_paths(self) -> IncidentSanitizationPolicy:
        paths = [rule.path for rule in self.rules]
        if len(paths) != len(set(paths)):
            raise ValueError("incident sanitization rule paths must be unique")
        return self


@dataclass(frozen=True)
class IncidentSanitizationResult:
    stream: EventStream
    transformed_fields: int
    dropped_fields: int


def sanitize_event_stream(
    stream: EventStream,
    policy: IncidentSanitizationPolicy,
    pseudonym_key: str,
) -> IncidentSanitizationResult:
    """Sanitize one event stream while preserving deterministic event order and correlation."""

    if len(pseudonym_key) < 16:
        raise ValueError("pseudonym key must contain at least 16 characters")

    rules = {rule.path: rule.action for rule in policy.rules}
    transformed = 0
    dropped = 0
    sanitized_events: list[BusinessEvent] = []

    for event in stream.events:
        payload, event_transformed, event_dropped = _sanitize_mapping(
            event.payload,
            rules=rules,
            policy=policy,
            pseudonym_key=pseudonym_key,
        )
        transformed += event_transformed
        dropped += event_dropped
        sanitized_events.append(
            BusinessEvent(
                event_id=_pseudonym("event", event.event_id, pseudonym_key),
                event_type=event.event_type,
                payload=payload,
            )
        )

    sanitized = EventStream(
        transaction_id=_pseudonym("transaction", stream.transaction_id, pseudonym_key),
        events=sanitized_events,
    )
    validate_sanitized_event_stream(sanitized)
    return IncidentSanitizationResult(
        stream=sanitized,
        transformed_fields=transformed,
        dropped_fields=dropped,
    )


def validate_sanitized_event_stream(stream: EventStream) -> None:
    """Fail closed if a sanitized replay fixture still exposes obvious secrets or PII."""

    if not stream.transaction_id.startswith("incident-transaction-"):
        raise ValueError("sanitized transaction_id must be an incident pseudonym")

    for event in stream.events:
        if not event.event_id.startswith("incident-event-"):
            raise ValueError("sanitized event_id must be an incident pseudonym")
        _validate_mapping(event.payload)


def _sanitize_mapping(
    payload: dict[str, Any],
    *,
    rules: dict[str, SanitizationAction],
    policy: IncidentSanitizationPolicy,
    pseudonym_key: str,
    prefix: str = "",
) -> tuple[dict[str, Any], int, int]:
    output: dict[str, Any] = {}
    transformed = 0
    dropped = 0

    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else key

        if _is_secret_path(path):
            dropped += 1
            continue

        action = rules.get(path)
        if action is None and isinstance(value, dict):
            nested, nested_transformed, nested_dropped = _sanitize_mapping(
                value,
                rules=rules,
                policy=policy,
                pseudonym_key=pseudonym_key,
                prefix=path,
            )
            transformed += nested_transformed
            dropped += nested_dropped
            if nested:
                output[key] = nested
            elif value:
                dropped += 1
            continue

        if action is None:
            dropped += 1
            continue

        sanitized_value = _apply_action(
            path,
            value,
            action=action,
            pii_detection=policy.pii_detection,
            pseudonym_key=pseudonym_key,
        )
        if sanitized_value is _DROP:
            dropped += 1
            continue

        output[key] = sanitized_value
        if action is not SanitizationAction.keep:
            transformed += 1

    return output, transformed, dropped


def _apply_action(
    path: str,
    value: Any,
    *,
    action: SanitizationAction,
    pii_detection: bool,
    pseudonym_key: str,
) -> Any:
    if action is SanitizationAction.drop:
        return _DROP
    if action is SanitizationAction.redact:
        return _REDACTED
    if action is SanitizationAction.tokenize:
        return _pseudonym(f"field:{path}", _canonical_value(value), pseudonym_key, prefix="token")

    if isinstance(value, (dict, list, tuple, set)):
        raise ValueError(f"keep action is only allowed for scalar fields: {path}")
    if pii_detection and (_is_pii_path(path) or _contains_pii(value)):
        raise ValueError(f"keep action would expose detected PII at field: {path}")
    return value


def _validate_mapping(payload: dict[str, Any], prefix: str = "") -> None:
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else key
        if _is_secret_path(path):
            raise ValueError(f"sanitized fixture still contains credential field: {path}")
        if isinstance(value, dict):
            _validate_mapping(value, path)
            continue
        if _is_pii_path(path) and not _is_transformed_value(value):
            raise ValueError(f"sanitized fixture still contains raw PII field: {path}")
        if _contains_pii(value) and not _is_transformed_value(value):
            raise ValueError(f"sanitized fixture still contains detected PII value at: {path}")


def _pseudonym(
    namespace: str,
    value: str,
    pseudonym_key: str,
    *,
    prefix: str = "incident",
) -> str:
    digest = hmac.new(
        pseudonym_key.encode("utf-8"),
        f"{namespace}:{value}".encode(),
        sha256,
    ).hexdigest()[:20]
    return f"{prefix}-{namespace.split(':', maxsplit=1)[0]}-{digest}"


def _canonical_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalized_path(path: str) -> str:
    return path.lower().replace("-", "_")


def _is_secret_path(path: str) -> bool:
    normalized = _normalized_path(path)
    return any(token in normalized for token in _SECRET_TOKENS)


def _is_pii_path(path: str) -> bool:
    normalized = _normalized_path(path)
    return any(token in normalized for token in _PII_TOKENS)


def _contains_pii(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    return bool(_EMAIL_PATTERN.fullmatch(candidate) or _PHONE_PATTERN.fullmatch(candidate))


def _is_transformed_value(value: Any) -> bool:
    return isinstance(value, str) and (value == _REDACTED or value.startswith("token-field-"))
