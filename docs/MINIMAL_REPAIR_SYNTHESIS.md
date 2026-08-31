# Deterministic Minimal Repair Synthesis

ERPChaos can verify whether a supplied recovery scenario restores business consistency. Minimal Repair Synthesis adds a different capability: given a known chaos-induced failure and an explicit catalog of allowed compensation templates, ERPChaos deterministically searches for the smallest repair plan that satisfies a Recovery Contract.

This is a bounded counterfactual search over fixtures. It is not an AI-generated runbook and it never executes writes against a production ERP.

## Reliability question

After chaos and causal lineage, ERPChaos can distinguish these two states even when both have the same net effect balance:

```text
Correct compensation:
  payment.received          active
  payment.received#dup1     compensated

Wrong compensation:
  payment.received          compensated
  payment.received#dup1     active
```

Minimal Repair Synthesis asks:

> From the explicitly allowed compensation candidates, what is the shortest deterministic plan that restores every recovery invariant?

## Repair catalog

A repair catalog defines the entire search space.

```yaml
schema: erpchaos.repair-catalog.v1
name: Property sale duplicate-payment repair catalog
max_plan_length: 1
max_evaluations: 5000
candidates:
  - name: reverse-original-payment
    event_type: payment.reversed
    payload:
      compensates_event_id: payment.received

  - name: reverse-duplicate-payment
    event_type: payment.reversed
    payload:
      compensates_event_id: payment.received#dup1
```

Candidate order is significant and deterministic. ERPChaos evaluates all one-step plans in catalog order before any two-step plan, all two-step plans before any three-step plan, and so on.

Repair v1 does not reuse the same candidate template within one plan. Plans are ordered permutations of distinct candidates.

## Search algorithm

The engine performs bounded breadth-first search by plan length:

```text
Known failed timeline
        |
        v
Length 1 plans, stable catalog order
        |
        +--> project history / effects / lineage
        +--> evaluate Recovery Contract
        |
        v
Length 2 plans
        |
       ...
        |
        v
First all-pass plan OR NO_REPAIR_FOUND
```

The first passing plan is therefore minimal by number of compensation events. Within the same plan length, catalog order provides a stable deterministic tie-breaker.

The same input stream, chaos scenario, repair catalog, Effect Map, Lineage Policy, and Recovery Contract always produce the same selected plan and search count.

## Hard search budget

`max_plan_length` is not the only bound. Permutations can grow quickly, so every catalog also has a hard `max_evaluations` budget.

Before synthesis begins, ERPChaos calculates the complete configured search-space size:

```text
P(n,1) + P(n,2) + ... + P(n,max_plan_length)
```

If that number exceeds `max_evaluations`, catalog validation fails before search execution.

Defaults and schema limits in v1:

- `max_plan_length`: 1 to 8
- candidate count: 1 to 12
- `max_evaluations`: defaults to 5,000 and is capped at 100,000

This keeps CI behavior predictable and prevents accidental combinatorial searches.

## Causal safety

A candidate is not accepted merely because aggregate arithmetic looks correct.

When an Effect Map and Lineage Policy are supplied, every candidate plan is projected through the existing Business Effect Ledger and causal compensation lineage engine. Invalid projections are rejected, and the Recovery Contract can require the exact surviving and compensated origins.

For duplicate payment recovery, the example Recovery Contract requires:

```yaml
- name: original-payment-remains-active
  path: lineage.payment.active_origin_ids
  operator: equals
  expected:
    - payment.received

- name: duplicate-payment-was-compensated
  path: lineage.payment.compensated_origin_ids
  operator: equals
  expected:
    - payment.received#dup1
```

A reversal targeting the original payment may restore `effects.payment.balance == 1`, but it still fails the causal recovery contract.

## CLI

Synthesize a minimal repair:

```bash
erpchaos repair synthesize \
  examples/real-estate/payment-effect.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-lineage-recovery.brc.yaml \
  examples/real-estate/payment-repair.catalog.yaml \
  --effect-map examples/real-estate/property-sale.effects.yaml \
  --lineage-policy examples/real-estate/property-sale.lineage.yaml
```

The command reports:

- `REPAIR_FOUND` or `NO_REPAIR_FOUND`
- number of evaluated plans
- selected candidate names
- deterministic generated repair event IDs
- selected plan length
- final Recovery Reliability Score
- final Recovery Contract invariant results

## Exit-code contract

- `0`: a repair plan was found and all recovery invariants pass
- `1`: the bounded catalog was exhausted without a valid repair
- `2`: invalid input, invalid catalog, non-failing starting chaos, or another configuration error

`NO_REPAIR_FOUND` is a business outcome, not a configuration error.

## Safety boundary

Minimal Repair Synthesis is intentionally constrained:

- no production writes
- no network calls
- no ERP credentials
- no LLM or AI service in search, ranking, linkage, or pass/fail
- explicit candidate catalog only
- bounded search only
- deterministic plan ordering
- deterministic generated event IDs
- existing recovery, Business Effect Ledger, and lineage engines are reused rather than reimplemented

The output is a tested repair fixture/plan. Applying that plan to a real system remains outside ERPChaos v0.12.

## Architecture

```text
Business Event Stream
        |
      Chaos
        |
        v
Known Failed Timeline
        |
        +------------------------------+
        |                              |
  Repair Catalog                 Recovery Contract
        |                              |
        v                              |
Bounded Plan Generator                 |
        |                              |
        v                              |
Candidate Timeline                     |
        |                              |
        +--> History Projection        |
        +--> Business Effect Ledger    |
        +--> Causal Lineage            |
        |                              |
        v                              v
        +------> Invariant Engine <-----+
                       |
                pass / continue
                       |
              first minimal pass
                       |
                       v
                 REPAIR_FOUND
```
