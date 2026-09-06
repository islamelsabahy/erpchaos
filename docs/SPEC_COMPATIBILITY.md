# ERPChaos Specification Compatibility

ERPChaos v0.15 introduces a deterministic registry and compatibility layer for public YAML specifications used by the reliability engine.

The goal is to make specification evolution explicit before `1.0`: a YAML file should have a known document kind, a canonical schema identity, deterministic validation, and a reproducible old-to-new compatibility result.

## Registered schemas

This build recognizes:

- `erpchaos.brc.v1` — Business Reliability Contract
- `erpchaos.recovery-contract.v1` — Recovery Contract
- `erpchaos.effect-map.v1` — Business Effect Map
- `erpchaos.effect-lineage.v1` — Causal Compensation Lineage Policy
- `erpchaos.repair-catalog.v1` — Minimal Repair Catalog
- `erpchaos.incident-sanitization-policy.v1` — Incident Sanitization Policy

The registry is deterministic and fail-closed. Explicit unsupported schema IDs are rejected rather than guessed.

```bash
erpchaos spec registry
```

## Legacy BRC and Recovery Contract files

BRC and Recovery Contract files predate explicit schema IDs. They remain valid in v0.15.

A legacy BRC like:

```yaml
name: Property Sale Reliability
version: "1"
transaction: property-sale
invariants:
  - name: payment-once
    path: history.types.payment_received.count
    operator: equals
    expected: 1
    severity: critical
```

is interpreted by the specification layer as `erpchaos.brc.v1`.

A legacy contract with:

```yaml
contract_type: recovery
```

is interpreted as `erpchaos.recovery-contract.v1`.

Normalization makes the implicit identity explicit without changing contract semantics:

```bash
erpchaos spec normalize legacy.brc.yaml --output canonical.brc.yaml
```

The canonical output begins with:

```yaml
schema: erpchaos.brc.v1
```

This migration is intentionally non-destructive: existing runtime contract files do not need to be rewritten immediately.

## Commands

### Inspect

Identify a document kind and canonical schema:

```bash
erpchaos spec inspect reliability/property-sale.brc.yaml
```

For deterministic machine-readable output:

```bash
erpchaos spec inspect reliability/property-sale.brc.yaml --json
```

### Validate

Validate a document using the authoritative ERPChaos Pydantic model registered for its schema:

```bash
erpchaos spec validate reliability/property-sale.brc.yaml
```

Invalid input, unsupported schemas, and malformed documents exit with code `2`.

### Normalize

Convert a valid document to canonical YAML:

```bash
erpchaos spec normalize \
  reliability/property-sale.brc.yaml \
  --output reliability/property-sale.canonical.brc.yaml
```

Normalization adds explicit schema identity for legacy BRC and Recovery Contract documents and uses the existing model serialization for already-versioned documents.

### Compare

Compare an old specification against a proposed new specification:

```bash
erpchaos spec compare old.yaml new.yaml
```

Machine-readable CI form:

```bash
erpchaos spec compare old.yaml new.yaml --json > spec-compatibility.json
```

The direction is always **old -> new**.

## Compatibility statuses

### `EXACT`

The canonical old and new documents are identical.

Exit code: `0`.

### `BACKWARD_COMPATIBLE`

The change is classified as safe for existing consumers under the rules defined for that document kind.

Examples:

- BRC description/name metadata changes with unchanged invariant semantics
- additive Effect Map effects or event contributions
- additive Lineage Policy compensation mappings

Exit code: `0`.

### `BEHAVIORAL_CHANGE`

The new document remains structurally valid but changes reliability behavior and should require explicit review.

Examples:

- adding an invariant to a BRC or Recovery Contract
- removing an invariant
- changing invariant severity
- semantic changes to registered policy types for which no stronger compatibility proof exists

Exit code: `1`.

A behavioral change is not automatically wrong. It is intentionally not reported as backward compatible because it can change CI outcomes.

### `INCOMPATIBLE`

The new document breaks an existing semantic contract or changes document identity.

Examples:

- comparing different document kinds
- changing canonical schema identity
- changing an existing invariant path/operator/expected value
- removing or changing an existing Effect Map contribution
- removing a Lineage Policy mapping
- changing a compensation target field

Exit code: `1`.

## Deterministic reports

Compatibility JSON uses the report schema:

```text
erpchaos.spec-compatibility.v1
```

Example:

```json
{"new":{"kind":"effect_map","legacy_implicit_schema":false,"name":"Property sale business effects with reservation","schema":"erpchaos.effect-map.v1"},"old":{"kind":"effect_map","legacy_implicit_schema":false,"name":"Property sale business effects","schema":"erpchaos.effect-map.v1"},"reasons":["effect added: reservation"],"schema":"erpchaos.spec-compatibility.v1","status":"BACKWARD_COMPATIBLE"}
```

Keys and reason ordering are deterministic. ERPChaos CI generates the same compatibility report on Python 3.11 and 3.12 and compares the bytes directly.

## Current comparison rules

### BRC and Recovery Contract

Comparison is invariant-name aware.

ERPChaos checks:

- transaction identity
- duplicate invariant names
- invariant additions/removals
- path
- operator
- literal expected value
- expected path
- severity

Changing the semantic tuple `(path, operator, expected, expected_path)` is incompatible. Adding/removing invariants or changing severity is classified as a behavioral change.

### Effect Map

Existing effects and event contributions must remain stable.

- adding an effect: backward compatible
- adding a contribution to an existing effect: backward compatible
- removing an effect/contribution: incompatible
- changing an existing signed contribution: incompatible

### Causal Compensation Lineage Policy

Existing effect mappings and compensation target fields must remain stable.

- additive effect/mapping: backward compatible
- removed effect/mapping: incompatible
- changed `target_field`: incompatible

### Repair Catalog and Incident Sanitization Policy

These specifications are validated through their authoritative models. In v0.15, metadata-only name changes are backward compatible; any other semantic difference is conservatively classified as `BEHAVIORAL_CHANGE`.

This is intentionally conservative until domain-specific compatibility rules are formalized.

## CI policy example

A repository can gate incompatible or behavior-changing changes with:

```bash
set +e
erpchaos spec compare main/reliability.yaml proposed/reliability.yaml --json > spec-report.json
status=$?
set -e

if [ "$status" -ne 0 ]; then
  cat spec-report.json
  exit "$status"
fi
```

Teams that intentionally tighten contracts can review the report and explicitly approve the change instead of silently accepting a different reliability policy.

## Safety and limitations

Specification compatibility is deterministic semantic comparison, not a formal proof that every external ERP consumer remains compatible.

Important boundaries:

- no AI/LLM participates in classification
- no network access is required
- no ERP or production state is mutated
- unsupported schemas fail closed
- normalization does not execute a workflow
- behavioral changes should be reviewed by the business/system owner
- Repair Catalog and Incident Policy compatibility is deliberately conservative in v0.15

## Direction to 1.0

The registry is the foundation for a stable public specification surface. Before `1.0`, future schema changes should introduce new explicit schema IDs rather than silently changing v1 semantics.
