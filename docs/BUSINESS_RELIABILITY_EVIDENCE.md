# Business Reliability Evidence Bundles

ERPChaos decisions can be deterministic while terminal output remains difficult for another system to archive, compare, or audit. Business Reliability Evidence Bundles (BREB) provide a versioned, machine-readable record of one reliability decision.

The bundle is deliberately not a log dump. It records the exact input-file digests, deterministic result fields, invariant outcomes, tool version, and a self-digest over the canonical evidence payload.

## Design goals

A core evidence bundle must be:

- deterministic across supported Python versions
- portable JSON
- independent from wall-clock time
- independently self-verifiable without a network call
- tied to exact input bytes through SHA-256
- free from automatically embedded ERP credentials or raw source documents
- suitable for CI artifacts and later audit workflows

## Schema

Current schema:

```text
erpchaos.evidence.v1
```

Representative repair evidence:

```json
{
  "schema": "erpchaos.evidence.v1",
  "tool_version": "0.13.0a0",
  "mode": "repair",
  "status": "REPAIR_FOUND",
  "input_digests": {
    "catalog": "sha256:...",
    "contract": "sha256:...",
    "effect_map": "sha256:...",
    "lineage_policy": "sha256:...",
    "recovery_contract": "sha256:...",
    "scenario": "sha256:...",
    "stream": "sha256:..."
  },
  "result": {
    "plan_length": 1,
    "score": 100,
    "searched_plan_count": 2,
    "selected_candidate_names": ["reverse-duplicate-payment"]
  },
  "invariants": [],
  "evidence_digest": "sha256:..."
}
```

The actual bundle includes every Recovery Contract invariant result in deterministic order.

## Canonical JSON

ERPChaos serializes core evidence using:

- UTF-8
- sorted object keys
- compact separators
- no NaN values
- one trailing newline in the written file

No timestamp, hostname, runner ID, username, random UUID, absolute path, or environment-specific field is included in the deterministic payload.

This enables byte-for-byte comparison of the same evidence generated on Python 3.11 and Python 3.12.

## Input digests

Input files are hashed from their exact raw bytes before evidence is built:

```text
sha256:<hex digest>
```

This intentionally means that even a whitespace or newline change changes the input digest and therefore the evidence self-digest.

The evidence bundle contains the digest, not the original source file contents.

## Evidence self-digest

`evidence_digest` is SHA-256 over the canonical JSON payload with `evidence_digest` omitted.

Verification therefore requires no external service:

```bash
erpchaos evidence verify /tmp/repair-evidence.json
```

If any protected payload field changes without recomputing the digest, verification exits with code `1`.

Malformed evidence exits with code `2`.

This is tamper detection, not cryptographic identity or signature verification. Signing and external attestations can be layered on later without changing the deterministic core schema.

## Repair evidence

Minimal Repair Synthesis can write evidence directly:

```bash
erpchaos repair synthesize \
  examples/real-estate/payment-effect.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-lineage-recovery.brc.yaml \
  examples/real-estate/payment-repair.catalog.yaml \
  --effect-map examples/real-estate/property-sale.effects.yaml \
  --lineage-policy examples/real-estate/property-sale.lineage.yaml \
  --evidence /tmp/repair-evidence.json
```

Evidence is written before the normal business exit code is returned. This means a `NO_REPAIR_FOUND` outcome can still produce durable evidence while the command exits with code `1`.

## Other reliability modes

The evidence API has centralized factories for:

- BRC verification
- chaos experiments
- recovery experiments
- minimal repair synthesis

The top-level evidence CLI can execute and capture the first three directly:

```bash
erpchaos evidence generate-verify CONTRACT STATE OUTPUT

erpchaos evidence generate-experiment \
  CONTRACT SCENARIO STREAM OUTPUT \
  --effect-map EFFECT_MAP \
  --lineage-policy LINEAGE_POLICY

erpchaos evidence generate-recovery \
  CONTRACT SCENARIO STREAM RECOVERY_CONTRACT RECOVERY_SCENARIO OUTPUT \
  --effect-map EFFECT_MAP \
  --lineage-policy LINEAGE_POLICY
```

These generation commands preserve ERPChaos business semantics: a valid bundle may still accompany exit code `1` when the evaluated business condition fails.

## CI proof of determinism

ERPChaos CI generates the same causal minimal-repair evidence independently under Python 3.11 and Python 3.12.

Each matrix job:

1. generates `repair-evidence.json`
2. verifies its self-digest
3. checks key schema/result fields
4. creates a tampered copy and proves verification fails
5. uploads the original evidence as a workflow artifact

A downstream job downloads both artifacts and runs byte-for-byte `cmp`.

The composite GitHub Action contract is allowed to run only after that cross-version consistency gate succeeds.

## Trust boundary

Business Reliability Evidence does not claim that:

- a source file came from a trusted person
- a CI runner was uncompromised
- an artifact was signed by a particular organization
- production data was truthful

It proves a narrower and useful property: the bundle is a deterministic ERPChaos result tied to specific input bytes, and its protected payload has not changed without changing the self-digest.

That makes it a suitable base layer for future signatures, attestations, release provenance, or policy-controlled deployment evidence.
