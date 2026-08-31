from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from erpchaos import __version__
from erpchaos.engine import InvariantResult

EvidenceMode = Literal["verify", "experiment", "recovery", "repair"]


class EvidenceInvariant(BaseModel):
    """Canonical invariant evidence independent from terminal formatting."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    actual: Any
    expected: Any
    severity: str
    expected_path: str | None = None


class BusinessReliabilityEvidence(BaseModel):
    """Deterministic machine-readable evidence for one ERPChaos decision."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["erpchaos.evidence.v1"] = Field(alias="schema")
    tool_version: str
    mode: EvidenceMode
    status: str
    input_digests: dict[str, str]
    result: dict[str, Any]
    invariants: list[EvidenceInvariant]
    evidence_digest: str


def sha256_file(path: Path) -> str:
    """Return a digest of the exact input bytes supplied to ERPChaos."""

    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def build_evidence(
    *,
    mode: EvidenceMode,
    status: str,
    input_paths: dict[str, Path],
    result: dict[str, Any],
    invariants: list[InvariantResult],
) -> BusinessReliabilityEvidence:
    """Build a deterministic evidence bundle from explicit inputs and results."""

    payload: dict[str, Any] = {
        "schema": "erpchaos.evidence.v1",
        "tool_version": __version__,
        "mode": mode,
        "status": status,
        "input_digests": {
            name: sha256_file(path) for name, path in sorted(input_paths.items())
        },
        "result": result,
        "invariants": [
            EvidenceInvariant(
                name=invariant.name,
                passed=invariant.passed,
                actual=invariant.actual,
                expected=invariant.expected,
                severity=invariant.severity,
                expected_path=invariant.expected_path,
            ).model_dump(mode="json")
            for invariant in invariants
        ],
    }
    payload["evidence_digest"] = _evidence_digest(payload)
    return BusinessReliabilityEvidence.model_validate(payload)


def canonical_evidence_json(evidence: BusinessReliabilityEvidence) -> str:
    """Serialize evidence using a stable canonical JSON representation."""

    return _canonical_json(evidence.model_dump(mode="json", by_alias=True)) + "\n"


def write_evidence(path: Path, evidence: BusinessReliabilityEvidence) -> None:
    """Write byte-stable evidence JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_evidence_json(evidence), encoding="utf-8")


def load_evidence(path: Path) -> BusinessReliabilityEvidence:
    """Load one evidence bundle from JSON."""

    data = json.loads(path.read_text(encoding="utf-8"))
    return BusinessReliabilityEvidence.model_validate(data)


def verify_evidence(evidence: BusinessReliabilityEvidence) -> bool:
    """Verify the evidence self-digest without external services."""

    payload = evidence.model_dump(mode="json", by_alias=True)
    expected = payload.pop("evidence_digest")
    return expected == _evidence_digest(payload)


def _evidence_digest(payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("evidence_digest", None)
    digest = sha256(_canonical_json(unsigned).encode()).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
