import json
from pathlib import Path

from erpchaos import __version__
from erpchaos.engine import InvariantResult
from erpchaos.evidence import (
    build_evidence,
    canonical_evidence_json,
    load_evidence,
    sha256_file,
    verify_evidence,
    write_evidence,
)


def _invariants() -> list[InvariantResult]:
    return [
        InvariantResult(
            name="one-effective-payment",
            passed=True,
            actual=1,
            expected=1,
            severity="critical",
        )
    ]


def test_same_inputs_produce_byte_identical_evidence(tmp_path: Path) -> None:
    contract = tmp_path / "contract.yaml"
    stream = tmp_path / "stream.yaml"
    contract.write_bytes(b"name: contract\n")
    stream.write_bytes(b"transaction_id: sale-001\n")

    first = build_evidence(
        mode="verify",
        status="PASS",
        input_paths={"stream": stream, "contract": contract},
        result={"score": 100},
        invariants=_invariants(),
    )
    second = build_evidence(
        mode="verify",
        status="PASS",
        input_paths={"contract": contract, "stream": stream},
        result={"score": 100},
        invariants=_invariants(),
    )

    assert canonical_evidence_json(first) == canonical_evidence_json(second)
    assert first.evidence_digest == second.evidence_digest
    assert first.tool_version == __version__
    assert list(first.input_digests) == ["contract", "stream"]


def test_changing_one_input_byte_changes_input_and_evidence_digest(tmp_path: Path) -> None:
    source = tmp_path / "stream.yaml"
    source.write_bytes(b"state: paid\n")

    first = build_evidence(
        mode="experiment",
        status="BUSINESS_FAILURE",
        input_paths={"stream": source},
        result={"score": 0},
        invariants=_invariants(),
    )
    first_input_digest = first.input_digests["stream"]

    source.write_bytes(b"state: paid \n")
    second = build_evidence(
        mode="experiment",
        status="BUSINESS_FAILURE",
        input_paths={"stream": source},
        result={"score": 0},
        invariants=_invariants(),
    )

    assert first_input_digest != second.input_digests["stream"]
    assert first.evidence_digest != second.evidence_digest


def test_tampered_payload_fails_self_digest_verification(tmp_path: Path) -> None:
    source = tmp_path / "contract.yaml"
    source.write_bytes(b"name: contract\n")
    evidence = build_evidence(
        mode="repair",
        status="REPAIR_FOUND",
        input_paths={"contract": source},
        result={"score": 100, "searched_plan_count": 2},
        invariants=_invariants(),
    )
    output = tmp_path / "evidence.json"
    write_evidence(output, evidence)

    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["result"]["score"] = 0
    output.write_text(json.dumps(payload), encoding="utf-8")

    tampered = load_evidence(output)
    assert verify_evidence(tampered) is False


def test_written_evidence_round_trips_and_verifies(tmp_path: Path) -> None:
    source = tmp_path / "catalog.yaml"
    source.write_bytes(b"schema: erpchaos.repair-catalog.v1\n")
    evidence = build_evidence(
        mode="repair",
        status="REPAIR_FOUND",
        input_paths={"catalog": source},
        result={
            "score": 100,
            "searched_plan_count": 2,
            "selected_candidate_names": ["reverse-duplicate-payment"],
        },
        invariants=_invariants(),
    )
    output = tmp_path / "evidence.json"

    write_evidence(output, evidence)
    loaded = load_evidence(output)

    assert verify_evidence(loaded) is True
    assert output.read_text(encoding="utf-8") == canonical_evidence_json(evidence)
    assert loaded.result["selected_candidate_names"] == ["reverse-duplicate-payment"]


def test_sha256_file_hashes_raw_bytes(tmp_path: Path) -> None:
    source = tmp_path / "input.bin"
    source.write_bytes(b"a\r\nb\n")
    first = sha256_file(source)

    source.write_bytes(b"a\nb\n")
    second = sha256_file(source)

    assert first.startswith("sha256:")
    assert first != second
