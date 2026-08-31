# Causal Compensation Lineage

ERPChaos Causal Compensation Lineage verifies **which business contribution a compensating event actually reverses**.

The Business Effect Ledger answers whether the final arithmetic is correct. Causal lineage answers whether the surviving and compensated contributions are the correct ones.

## Why net balance is not enough

Consider a duplicate callback:

```text
payment.received          # original payment contribution
payment.received#dup1     # duplicate contribution created by retry
```

The Business Effect Ledger reports a payment balance of `2`.

Now add one reversal. Both of these histories end at payment balance `1`:

```text
Correct compensation
--------------------
payment.received          active
payment.received#dup1     compensated

Wrong compensation
------------------
payment.received          compensated
payment.received#dup1     active
```

Arithmetic alone cannot distinguish those outcomes.

Causal lineage can.

## Lineage policy

A lineage policy declares how compensating event types identify the event they reverse.

```yaml
schema: erpchaos.effect-lineage.v1
name: Property sale compensation lineage
effects:
  payment:
    compensation_events:
      payment.reversed:
        target_field: compensates_event_id
```

The policy is evaluated together with an Effect Map. In lineage v1, all contributions for a lineage-enabled effect must be unit contributions:

- `+1` = one origin contribution
- `-1` = one compensating contribution

This intentionally creates a one-to-one provenance model rather than an ambiguous many-to-many arithmetic model.

## Recovery fixture

A compensating event carries the target origin ID in the configured payload field:

```yaml
name: Reverse duplicate payment by causal target
events:
  - event_id: payment.reversed
    event_type: payment.reversed
    payload:
      compensates_event_id: payment.received#dup1
```

The target must refer to a **prior positive contribution** for the same effect.

## Projected state

For a correct duplicate-payment compensation, ERPChaos can project:

```yaml
lineage:
  payment:
    origin_count: 2
    compensation_count: 1
    linked_compensation_count: 1
    orphan_compensation_count: 0
    missing_reference_count: 0
    unknown_reference_count: 0
    future_reference_count: 0
    non_origin_reference_count: 0
    duplicate_compensation_count: 0
    active_origin_ids:
      - payment.received
    compensated_origin_ids:
      - payment.received#dup1
    valid: true
```

The ordered origin-ID lists are intentionally exposed to the contract engine. A Recovery Contract can verify exact provenance, not just aggregate counts.

## What `valid` means

`lineage.<effect>.valid` verifies structural causal integrity.

It becomes false when ERPChaos detects any of these conditions:

- a compensation has no target reference;
- the target event does not exist;
- the target event occurs later in the timeline;
- the target is not a positive origin contribution for that effect;
- the same origin is compensated more than once.

A structurally valid lineage can still be **business-wrong**.

For example, reversing the original payment instead of the duplicate is a valid link to a prior positive contribution. ERPChaos therefore keeps `valid: true`, but exposes:

```yaml
active_origin_ids:
  - payment.received#dup1
compensated_origin_ids:
  - payment.received
```

A Recovery Contract can then reject the wrong target explicitly.

This distinction is deliberate:

- the lineage engine verifies causal structure;
- the business contract verifies whether the chosen causal target is correct for the workflow.

## Error counters

Each lineage-enabled effect exposes deterministic counters:

| Field | Meaning |
| --- | --- |
| `origin_count` | Positive unit contributions observed |
| `compensation_count` | Negative unit contributions observed |
| `linked_compensation_count` | Compensations successfully linked to prior origins |
| `orphan_compensation_count` | Missing, unknown, future, or non-origin references |
| `missing_reference_count` | Compensation did not supply its configured target field |
| `unknown_reference_count` | Target event ID does not exist |
| `future_reference_count` | Target event exists but occurs after the compensation |
| `non_origin_reference_count` | Target exists but is not a positive origin for the effect |
| `duplicate_compensation_count` | A previously compensated origin was targeted again |
| `active_origin_ids` | Origins not compensated by the end of the timeline |
| `compensated_origin_ids` | Origins successfully compensated, in compensation order |
| `valid` | No structural lineage error was detected |

## Contract example

A duplicate-payment recovery contract can combine arithmetic and provenance:

```yaml
invariants:
  - name: one-effective-payment
    path: effects.payment.balance
    operator: equals
    expected: 1
    severity: critical

  - name: compensation-lineage-valid
    path: lineage.payment.valid
    operator: equals
    expected: true
    severity: critical

  - name: original-payment-remains-active
    path: lineage.payment.active_origin_ids
    operator: equals
    expected:
      - payment.received
    severity: critical

  - name: duplicate-payment-was-compensated
    path: lineage.payment.compensated_origin_ids
    operator: equals
    expected:
      - payment.received#dup1
    severity: critical
```

The first invariant alone cannot distinguish a correct target from a wrong one. The lineage invariants close that gap.

## CLI

Project lineage directly:

```bash
erpchaos lineage project \
  examples/real-estate/payment-lineage.events.yaml \
  examples/real-estate/property-sale.effects.yaml \
  examples/real-estate/property-sale.lineage.yaml
```

Run causal recovery:

```bash
erpchaos recovery run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-lineage-recovery.brc.yaml \
  examples/real-estate/payment-lineage-correct.recovery.yaml \
  --effect-map examples/real-estate/property-sale.effects.yaml \
  --lineage-policy examples/real-estate/property-sale.lineage.yaml
```

The `--lineage-policy` option requires an Effect Map because lineage is defined over effect contributions.

## Deterministic safety boundary

Lineage v1 deliberately stays narrow:

- unit contributions only (`+1` and `-1`);
- one compensation targets one prior origin;
- event IDs must be unique;
- target references are fixture data, never live production mutations;
- no timing heuristics;
- no AI or LLM participates in linkage or pass/fail.

This boundary keeps provenance auditable and reproducible in CI before future versions consider richer cardinality or value-aware causal graphs.
