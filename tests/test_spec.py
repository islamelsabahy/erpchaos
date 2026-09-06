from __future__ import annotations

import json

import pytest

from erpchaos.spec import (
    CompatibilityStatus,
    DocumentKind,
    compare_specs,
    compatibility_json,
    inspect_spec,
    normalize_spec,
)


def _brc(*, description: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Property Sale Contract",
        "version": "1",
        "transaction": "property-sale",
        "invariants": [
            {
                "name": "payment-once",
                "path": "history.types.payment_received.count",
                "operator": "equals",
                "expected": 1,
                "severity": "critical",
            }
        ],
    }
    if description is not None:
        payload["description"] = description
    return payload


def _recovery_contract() -> dict[str, object]:
    return {
        "name": "Payment Recovery Contract",
        "version": "1",
        "transaction": "property-sale-recovery",
        "contract_type": "recovery",
        "invariants": [
            {
                "name": "one-effective-payment",
                "path": "effects.payment.balance",
                "operator": "equals",
                "expected": 1,
                "severity": "critical",
            }
        ],
    }


def _effect_map() -> dict[str, object]:
    return {
        "schema": "erpchaos.effect-map.v1",
        "name": "Property sale effects",
        "effects": {
            "payment": {
                "contributions": {
                    "payment.received": 1,
                    "payment.reversed": -1,
                }
            }
        },
    }


def test_legacy_brc_inspection_and_normalization_add_explicit_schema() -> None:
    inspection = inspect_spec(_brc())

    assert inspection.kind is DocumentKind.brc
    assert inspection.schema == "erpchaos.brc.v1"
    assert inspection.legacy_implicit_schema is True

    normalized = normalize_spec(_brc())
    assert normalized["schema"] == "erpchaos.brc.v1"
    assert normalized["transaction"] == "property-sale"


def test_legacy_recovery_contract_normalizes_to_recovery_schema() -> None:
    inspection = inspect_spec(_recovery_contract())
    normalized = normalize_spec(_recovery_contract())

    assert inspection.kind is DocumentKind.recovery_contract
    assert inspection.schema == "erpchaos.recovery-contract.v1"
    assert inspection.legacy_implicit_schema is True
    assert normalized["schema"] == "erpchaos.recovery-contract.v1"
    assert normalized["contract_type"] == "recovery"


def test_explicit_brc_schema_is_not_legacy() -> None:
    payload = _brc()
    payload["schema"] = "erpchaos.brc.v1"

    inspection = inspect_spec(payload)

    assert inspection.kind is DocumentKind.brc
    assert inspection.legacy_implicit_schema is False


def test_unsupported_schema_fails_closed() -> None:
    payload = _brc()
    payload["schema"] = "erpchaos.brc.v99"

    with pytest.raises(ValueError, match="unsupported ERPChaos schema"):
        inspect_spec(payload)


def test_contract_metadata_only_change_is_backward_compatible() -> None:
    report = compare_specs(_brc(description="old"), _brc(description="new"))

    assert report.status is CompatibilityStatus.backward_compatible
    assert report.reasons == ["only contract metadata changed"]


def test_added_contract_invariant_is_behavioral_tightening() -> None:
    new = _brc()
    invariants = list(new["invariants"])  # type: ignore[arg-type]
    invariants.append(
        {
            "name": "finance-before-payment",
            "path": "history.types.finance_approved.first_position",
            "operator": "before",
            "expected_path": "history.types.payment_received.first_position",
            "severity": "critical",
        }
    )
    new["invariants"] = invariants

    report = compare_specs(_brc(), new)

    assert report.status is CompatibilityStatus.behavioral_change
    assert report.reasons == ["invariant added: finance-before-payment"]


def test_changed_invariant_semantics_are_incompatible() -> None:
    new = _brc()
    invariants = list(new["invariants"])  # type: ignore[arg-type]
    changed = dict(invariants[0])
    changed["expected"] = 2
    new["invariants"] = [changed]

    report = compare_specs(_brc(), new)

    assert report.status is CompatibilityStatus.incompatible
    assert report.reasons == ["invariant semantics changed: payment-once"]


def test_additive_effect_mapping_is_backward_compatible() -> None:
    new = _effect_map()
    effects = dict(new["effects"])  # type: ignore[arg-type]
    effects["reservation"] = {"contributions": {"reservation.created": 1}}
    new["effects"] = effects

    report = compare_specs(_effect_map(), new)

    assert report.status is CompatibilityStatus.backward_compatible
    assert report.reasons == ["effect added: reservation"]


def test_changed_effect_contribution_is_incompatible() -> None:
    new = _effect_map()
    effects = dict(new["effects"])  # type: ignore[arg-type]
    payment = dict(effects["payment"])
    contributions = dict(payment["contributions"])
    contributions["payment.received"] = 2
    payment["contributions"] = contributions
    effects["payment"] = payment
    new["effects"] = effects

    report = compare_specs(_effect_map(), new)

    assert report.status is CompatibilityStatus.incompatible
    assert report.reasons == ["effect contribution changed: payment:payment.received: 1 -> 2"]


def test_wrong_document_kind_is_incompatible() -> None:
    report = compare_specs(_brc(), _effect_map())

    assert report.status is CompatibilityStatus.incompatible
    assert report.reasons == ["document kind changed: brc -> effect_map"]


def test_compatibility_json_is_byte_stable() -> None:
    report = compare_specs(_brc(description="old"), _brc(description="new"))

    first = compatibility_json(report)
    second = compatibility_json(report)

    assert first == second
    assert first.endswith("\n")
    payload = json.loads(first)
    assert payload["schema"] == "erpchaos.spec-compatibility.v1"
    assert payload["status"] == "BACKWARD_COMPATIBLE"
