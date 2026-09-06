from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from erpchaos.effects import EffectMap
from erpchaos.incidents import IncidentSanitizationPolicy
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.models import BusinessReliabilityContract, Invariant
from erpchaos.recovery import RecoveryContract
from erpchaos.repair import RepairCatalog


class DocumentKind(StrEnum):
    brc = "brc"
    recovery_contract = "recovery_contract"
    effect_map = "effect_map"
    effect_lineage = "effect_lineage"
    repair_catalog = "repair_catalog"
    incident_sanitization_policy = "incident_sanitization_policy"


class CompatibilityStatus(StrEnum):
    exact = "EXACT"
    backward_compatible = "BACKWARD_COMPATIBLE"
    behavioral_change = "BEHAVIORAL_CHANGE"
    incompatible = "INCOMPATIBLE"


class SpecInspection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: DocumentKind
    schema_version: str = Field(alias="schema")
    legacy_implicit_schema: bool
    name: str | None = None


class CompatibilityReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    report_schema: Literal["erpchaos.spec-compatibility.v1"] = Field(
        default="erpchaos.spec-compatibility.v1",
        alias="schema",
    )
    old: SpecInspection
    new: SpecInspection
    status: CompatibilityStatus
    reasons: list[str]


@dataclass(frozen=True)
class _SchemaDescriptor:
    kind: DocumentKind
    schema: str
    model: type[BaseModel]


@dataclass(frozen=True)
class ValidatedSpec:
    inspection: SpecInspection
    model: BaseModel
    canonical: dict[str, Any]


_SCHEMA_REGISTRY: dict[str, _SchemaDescriptor] = {
    "erpchaos.brc.v1": _SchemaDescriptor(
        kind=DocumentKind.brc,
        schema="erpchaos.brc.v1",
        model=BusinessReliabilityContract,
    ),
    "erpchaos.recovery-contract.v1": _SchemaDescriptor(
        kind=DocumentKind.recovery_contract,
        schema="erpchaos.recovery-contract.v1",
        model=RecoveryContract,
    ),
    "erpchaos.effect-map.v1": _SchemaDescriptor(
        kind=DocumentKind.effect_map,
        schema="erpchaos.effect-map.v1",
        model=EffectMap,
    ),
    "erpchaos.effect-lineage.v1": _SchemaDescriptor(
        kind=DocumentKind.effect_lineage,
        schema="erpchaos.effect-lineage.v1",
        model=EffectLineagePolicy,
    ),
    "erpchaos.repair-catalog.v1": _SchemaDescriptor(
        kind=DocumentKind.repair_catalog,
        schema="erpchaos.repair-catalog.v1",
        model=RepairCatalog,
    ),
    "erpchaos.incident-sanitization-policy.v1": _SchemaDescriptor(
        kind=DocumentKind.incident_sanitization_policy,
        schema="erpchaos.incident-sanitization-policy.v1",
        model=IncidentSanitizationPolicy,
    ),
}

_CONTRACT_KINDS = {DocumentKind.brc, DocumentKind.recovery_contract}


def registered_schemas() -> tuple[str, ...]:
    return tuple(sorted(_SCHEMA_REGISTRY))


def validate_spec(data: dict[str, Any]) -> ValidatedSpec:
    descriptor, legacy = _resolve_descriptor(data)
    validation_data = dict(data)
    if descriptor.kind in _CONTRACT_KINDS:
        validation_data.pop("schema", None)

    model = descriptor.model.model_validate(validation_data)
    canonical = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    if descriptor.kind in _CONTRACT_KINDS:
        canonical = {"schema": descriptor.schema, **canonical}

    inspection = SpecInspection(
        kind=descriptor.kind,
        schema_version=descriptor.schema,
        legacy_implicit_schema=legacy,
        name=_document_name(model),
    )
    return ValidatedSpec(inspection=inspection, model=model, canonical=canonical)


def inspect_spec(data: dict[str, Any]) -> SpecInspection:
    return validate_spec(data).inspection


def normalize_spec(data: dict[str, Any]) -> dict[str, Any]:
    return validate_spec(data).canonical


def compare_specs(old_data: dict[str, Any], new_data: dict[str, Any]) -> CompatibilityReport:
    old = validate_spec(old_data)
    new = validate_spec(new_data)

    if old.inspection.kind is not new.inspection.kind:
        return _report(
            old,
            new,
            CompatibilityStatus.incompatible,
            [
                "document kind changed: "
                f"{old.inspection.kind.value} -> {new.inspection.kind.value}"
            ],
        )

    if old.inspection.schema_version != new.inspection.schema_version:
        return _report(
            old,
            new,
            CompatibilityStatus.incompatible,
            [
                "schema changed: "
                f"{old.inspection.schema_version} -> {new.inspection.schema_version}"
            ],
        )

    if old.canonical == new.canonical:
        return _report(old, new, CompatibilityStatus.exact, [])

    kind = old.inspection.kind
    if kind in _CONTRACT_KINDS:
        return _compare_contracts(old, new)
    if kind is DocumentKind.effect_map:
        return _compare_effect_maps(old, new)
    if kind is DocumentKind.effect_lineage:
        return _compare_lineage_policies(old, new)
    return _compare_policy_documents(old, new)


def compatibility_json(report: CompatibilityReport) -> str:
    payload = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _resolve_descriptor(data: dict[str, Any]) -> tuple[_SchemaDescriptor, bool]:
    declared = data.get("schema")
    if declared is not None:
        if not isinstance(declared, str) or not declared.strip():
            raise ValueError("schema must be a non-empty string")
        descriptor = _SCHEMA_REGISTRY.get(declared)
        if descriptor is None:
            supported = ", ".join(registered_schemas())
            raise ValueError(f"unsupported ERPChaos schema: {declared}; supported: {supported}")
        return descriptor, False

    if _looks_like_contract(data):
        if data.get("contract_type") == "recovery":
            return _SCHEMA_REGISTRY["erpchaos.recovery-contract.v1"], True
        return _SCHEMA_REGISTRY["erpchaos.brc.v1"], True

    supported = ", ".join(registered_schemas())
    raise ValueError(
        "document has no supported schema and is not a legacy BRC/Recovery Contract; "
        f"supported: {supported}"
    )


def _looks_like_contract(data: dict[str, Any]) -> bool:
    return "transaction" in data and "invariants" in data


def _document_name(model: BaseModel) -> str | None:
    name = getattr(model, "name", None)
    return name if isinstance(name, str) else None


def _report(
    old: ValidatedSpec,
    new: ValidatedSpec,
    status: CompatibilityStatus,
    reasons: list[str],
) -> CompatibilityReport:
    return CompatibilityReport(
        old=old.inspection,
        new=new.inspection,
        status=status,
        reasons=reasons,
    )


def _compare_contracts(old: ValidatedSpec, new: ValidatedSpec) -> CompatibilityReport:
    old_contract = cast(BusinessReliabilityContract, old.model)
    new_contract = cast(BusinessReliabilityContract, new.model)
    reasons: list[str] = []
    incompatible = False
    behavioral = False

    if old_contract.transaction != new_contract.transaction:
        incompatible = True
        reasons.append(
            f"transaction changed: {old_contract.transaction} -> {new_contract.transaction}"
        )

    old_map, old_duplicates = _invariant_map(old_contract.invariants)
    new_map, new_duplicates = _invariant_map(new_contract.invariants)
    if old_duplicates:
        incompatible = True
        reasons.append("old contract has duplicate invariant names: " + ", ".join(old_duplicates))
    if new_duplicates:
        incompatible = True
        reasons.append("new contract has duplicate invariant names: " + ", ".join(new_duplicates))

    for name in sorted(old_map):
        if name not in new_map:
            behavioral = True
            reasons.append(f"invariant removed: {name}")
            continue
        old_invariant = old_map[name]
        new_invariant = new_map[name]
        if _invariant_semantics(old_invariant) != _invariant_semantics(new_invariant):
            incompatible = True
            reasons.append(f"invariant semantics changed: {name}")
        elif old_invariant.severity != new_invariant.severity:
            behavioral = True
            reasons.append(
                f"invariant severity changed: {name}: "
                f"{old_invariant.severity.value} -> {new_invariant.severity.value}"
            )

    for name in sorted(set(new_map) - set(old_map)):
        behavioral = True
        reasons.append(f"invariant added: {name}")

    if incompatible:
        status = CompatibilityStatus.incompatible
    elif behavioral:
        status = CompatibilityStatus.behavioral_change
    else:
        status = CompatibilityStatus.backward_compatible
        reasons.append("only contract metadata changed")
    return _report(old, new, status, reasons)


def _invariant_map(invariants: list[Invariant]) -> tuple[dict[str, Invariant], list[str]]:
    mapped: dict[str, Invariant] = {}
    duplicates: set[str] = set()
    for invariant in invariants:
        if invariant.name in mapped:
            duplicates.add(invariant.name)
        mapped[invariant.name] = invariant
    return mapped, sorted(duplicates)


def _invariant_semantics(invariant: Invariant) -> tuple[Any, ...]:
    return (
        invariant.path,
        invariant.operator.value,
        invariant.expected,
        invariant.expected_path,
    )


def _compare_effect_maps(old: ValidatedSpec, new: ValidatedSpec) -> CompatibilityReport:
    old_map = cast(EffectMap, old.model)
    new_map = cast(EffectMap, new.model)
    reasons: list[str] = []
    incompatible = False
    additive = False

    for effect_name in sorted(old_map.effects):
        if effect_name not in new_map.effects:
            incompatible = True
            reasons.append(f"effect removed: {effect_name}")
            continue
        old_contributions = old_map.effects[effect_name].contributions
        new_contributions = new_map.effects[effect_name].contributions
        for event_type in sorted(old_contributions):
            if event_type not in new_contributions:
                incompatible = True
                reasons.append(f"effect contribution removed: {effect_name}:{event_type}")
            elif old_contributions[event_type] != new_contributions[event_type]:
                incompatible = True
                reasons.append(
                    "effect contribution changed: "
                    f"{effect_name}:{event_type}: "
                    f"{old_contributions[event_type]} -> {new_contributions[event_type]}"
                )
        for event_type in sorted(set(new_contributions) - set(old_contributions)):
            additive = True
            reasons.append(f"effect contribution added: {effect_name}:{event_type}")

    for effect_name in sorted(set(new_map.effects) - set(old_map.effects)):
        additive = True
        reasons.append(f"effect added: {effect_name}")

    if incompatible:
        status = CompatibilityStatus.incompatible
    elif additive:
        status = CompatibilityStatus.backward_compatible
    else:
        status = CompatibilityStatus.backward_compatible
        reasons.append("only effect-map metadata changed")
    return _report(old, new, status, reasons)


def _compare_lineage_policies(old: ValidatedSpec, new: ValidatedSpec) -> CompatibilityReport:
    old_policy = cast(EffectLineagePolicy, old.model)
    new_policy = cast(EffectLineagePolicy, new.model)
    reasons: list[str] = []
    incompatible = False
    additive = False

    for effect_name in sorted(old_policy.effects):
        if effect_name not in new_policy.effects:
            incompatible = True
            reasons.append(f"lineage effect removed: {effect_name}")
            continue
        old_events = old_policy.effects[effect_name].compensation_events
        new_events = new_policy.effects[effect_name].compensation_events
        for event_type in sorted(old_events):
            if event_type not in new_events:
                incompatible = True
                reasons.append(f"compensation mapping removed: {effect_name}:{event_type}")
            elif old_events[event_type].target_field != new_events[event_type].target_field:
                incompatible = True
                reasons.append(
                    "compensation target field changed: "
                    f"{effect_name}:{event_type}: "
                    f"{old_events[event_type].target_field} -> "
                    f"{new_events[event_type].target_field}"
                )
        for event_type in sorted(set(new_events) - set(old_events)):
            additive = True
            reasons.append(f"compensation mapping added: {effect_name}:{event_type}")

    for effect_name in sorted(set(new_policy.effects) - set(old_policy.effects)):
        additive = True
        reasons.append(f"lineage effect added: {effect_name}")

    if incompatible:
        status = CompatibilityStatus.incompatible
    elif additive:
        status = CompatibilityStatus.backward_compatible
    else:
        status = CompatibilityStatus.backward_compatible
        reasons.append("only lineage-policy metadata changed")
    return _report(old, new, status, reasons)


def _compare_policy_documents(old: ValidatedSpec, new: ValidatedSpec) -> CompatibilityReport:
    old_semantics = {key: value for key, value in old.canonical.items() if key != "name"}
    new_semantics = {key: value for key, value in new.canonical.items() if key != "name"}
    if old_semantics == new_semantics:
        return _report(
            old,
            new,
            CompatibilityStatus.backward_compatible,
            ["only document metadata changed"],
        )
    return _report(
        old,
        new,
        CompatibilityStatus.behavioral_change,
        ["registered policy semantics changed; no stronger backward-compatibility rule is defined"],
    )
