from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erpchaos.effects import EffectMap
from erpchaos.events import BusinessEvent


class CompensationLinkRule(BaseModel):
    """Declare where a compensating event stores the origin event ID it reverses."""

    model_config = ConfigDict(extra="forbid")

    target_field: str = Field(min_length=1)


class EffectLineageDefinition(BaseModel):
    """Compensation-event linkage rules for one Business Effect Ledger effect."""

    model_config = ConfigDict(extra="forbid")

    compensation_events: dict[str, CompensationLinkRule] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_event_types(self) -> EffectLineageDefinition:
        if any(not event_type.strip() for event_type in self.compensation_events):
            raise ValueError("lineage compensation event types must not be empty")
        return self


class EffectLineagePolicy(BaseModel):
    """Vendor-neutral causal linkage rules for compensating business effects."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.effect-lineage.v1"] = Field(alias="schema")
    name: str = Field(min_length=1)
    effects: dict[str, EffectLineageDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_effect_names(self) -> EffectLineagePolicy:
        if any(not effect_name.strip() for effect_name in self.effects):
            raise ValueError("lineage effect names must not be empty")
        return self


def project_compensation_lineage(
    events: list[BusinessEvent],
    effect_map: EffectMap,
    policy: EffectLineagePolicy,
) -> dict[str, object]:
    """Project deterministic one-to-one causal lineage for business compensations."""

    event_positions = _event_positions(events)
    projected: dict[str, dict[str, Any]] = {}

    for effect_name, lineage_definition in policy.effects.items():
        if effect_name not in effect_map.effects:
            raise ValueError(f"lineage effect is missing from effect map: {effect_name}")

        effect_definition = effect_map.effects[effect_name]
        _validate_unit_lineage_definition(
            effect_name,
            effect_definition.contributions,
            lineage_definition,
        )

        origins: list[str] = []
        compensated_origins: list[str] = []
        compensated_set: set[str] = set()
        compensation_count = 0
        linked_compensation_count = 0
        missing_reference_count = 0
        unknown_reference_count = 0
        future_reference_count = 0
        non_origin_reference_count = 0
        duplicate_compensation_count = 0

        for position, event in enumerate(events, start=1):
            delta = effect_definition.contributions.get(event.event_type)
            if delta is None:
                continue

            if delta == 1:
                origins.append(event.event_id)
                continue

            compensation_count += 1
            rule = lineage_definition.compensation_events[event.event_type]
            target = _resolve_payload_field(event.payload, rule.target_field)
            if not isinstance(target, str) or not target.strip():
                missing_reference_count += 1
                continue

            target_position = event_positions.get(target)
            if target_position is None:
                unknown_reference_count += 1
                continue
            if target_position >= position:
                future_reference_count += 1
                continue

            target_event = events[target_position - 1]
            target_delta = effect_definition.contributions.get(target_event.event_type)
            if target_delta != 1:
                non_origin_reference_count += 1
                continue

            if target in compensated_set:
                duplicate_compensation_count += 1
                continue

            compensated_set.add(target)
            compensated_origins.append(target)
            linked_compensation_count += 1

        active_origins = [origin for origin in origins if origin not in compensated_set]
        orphan_compensation_count = (
            missing_reference_count
            + unknown_reference_count
            + future_reference_count
            + non_origin_reference_count
        )
        valid = orphan_compensation_count == 0 and duplicate_compensation_count == 0

        projected[effect_name] = {
            "origin_count": len(origins),
            "compensation_count": compensation_count,
            "linked_compensation_count": linked_compensation_count,
            "orphan_compensation_count": orphan_compensation_count,
            "missing_reference_count": missing_reference_count,
            "unknown_reference_count": unknown_reference_count,
            "future_reference_count": future_reference_count,
            "non_origin_reference_count": non_origin_reference_count,
            "duplicate_compensation_count": duplicate_compensation_count,
            "active_origin_ids": active_origins,
            "compensated_origin_ids": compensated_origins,
            "valid": valid,
        }

    return {"lineage": projected}


def _event_positions(events: list[BusinessEvent]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for position, event in enumerate(events, start=1):
        if event.event_id in positions:
            raise ValueError(f"lineage requires unique event IDs: {event.event_id}")
        positions[event.event_id] = position
    return positions


def _validate_unit_lineage_definition(
    effect_name: str,
    contributions: dict[str, int],
    lineage_definition: EffectLineageDefinition,
) -> None:
    if any(delta not in {-1, 1} for delta in contributions.values()):
        raise ValueError(
            f"lineage v1 requires unit contributions (+1/-1) for effect: {effect_name}"
        )

    negative_events = {event_type for event_type, delta in contributions.items() if delta == -1}
    configured_events = set(lineage_definition.compensation_events)
    if configured_events != negative_events:
        missing = sorted(negative_events - configured_events)
        unexpected = sorted(configured_events - negative_events)
        details: list[str] = []
        if missing:
            details.append(f"missing compensation rules: {', '.join(missing)}")
        if unexpected:
            details.append(f"non-negative compensation rules: {', '.join(unexpected)}")
        raise ValueError(f"invalid lineage rules for {effect_name}: {'; '.join(details)}")


def _resolve_payload_field(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
