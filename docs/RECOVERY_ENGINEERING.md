# Business Recovery Engineering

ERPChaos does not stop at detecting that a business transaction became inconsistent after chaos. The recovery engine verifies whether explicit compensating business events can restore a valid transaction state, how many deterministic recovery steps are required, and whether that recovered state remains stable.

## Why recovery is a separate reliability problem

Infrastructure recovery and business recovery are not the same thing.

A service can restart successfully, a queue can drain, and every health check can return green while the ERP still contains a duplicated payment, duplicated commission, invalid approval order, or another financially inconsistent state.

ERPChaos therefore models recovery as an executable business-reliability experiment:

```text
Baseline EventStream
        |
        v
Chaos Scenario
        |
        v
Known Business Failure
        |
        v
Ordered Recovery Events
        |
        +---- checkpoint 1 -> Recovery Contract -> RRS
        |
        +---- checkpoint 2 -> Recovery Contract -> RRS
        |
        +---- checkpoint N -> Recovery Contract -> RRS
        |
        v
Final Recovery Classification
```

No wall-clock sleeps, timing races, production writes, or AI decisions are involved.

## Recovery Contract

A `RecoveryContract` uses the same deterministic invariant engine as a Business Reliability Contract, but its invariants describe what must be true after compensation.

Example for a duplicate-payment incident:

```yaml
name: Duplicate Payment Recovery Contract
version: "1"
transaction: property-sale-payment-recovery
contract_type: recovery
invariants:
  - name: one-effective-payment
    path: history.types.payment_received.count
    operator: equals
    expected: 2
    severity: critical

  - name: exactly-one-payment-reversal
    path: history.types.payment_reversed.count
    operator: equals
    expected: 1
    severity: critical
```

The recovery contract is explicit. ERPChaos does not infer whether a transaction is recovered from a model response or heuristic narrative.

## Recovery Scenario

A recovery scenario is an ordered list of compensating events applied after the chaos phase has already produced a failing business state.

```yaml
name: Reverse duplicated payment

events:
  - event_id: recovery.payment-reversed.001
    event_type: payment.reversed
    payload:
      reason: duplicate-payment-compensation
```

Recovery event IDs must be unique and cannot reuse IDs already present in the post-chaos event stream.

Recovery events are fixtures only. ERPChaos does not execute compensating writes against a production ERP.

## Recovery Reliability Score (RRS)

At every recovery checkpoint, ERPChaos evaluates the Recovery Contract and calculates a severity-weighted score from `0` to `100`.

The weighting model matches the deterministic reliability engine:

| Severity | Weight |
| --- | ---: |
| low | 1 |
| medium | 2 |
| high | 4 |
| critical | 8 |

A score of `100` means every recovery invariant passes at that checkpoint.

## Time to Business Consistency (TTBC)

`TTBC` is the first deterministic recovery-event step at which every recovery invariant passes.

It is deliberately **not wall-clock time**.

Example:

```text
Post-chaos state      RRS 50   inconsistent
Recovery event #1     RRS 100  consistent  <-- TTBC = 1
Recovery event #2     RRS 50   inconsistent again
```

For the same input event stream and recovery scenario, TTBC is reproducible in CI.

This makes the metric useful even when test runners, CPUs, queues, or network environments have different timing characteristics.

## Recovery classifications

ERPChaos classifies the final recovery state as:

| Status | Meaning |
| --- | --- |
| `RECOVERED` | Every final recovery invariant passes |
| `PARTIALLY_RECOVERED` | At least one final invariant passes, but the transaction is still inconsistent |
| `UNRECOVERED` | No final recovery invariant passes |

Business-recovery failure exits with code `1`, so it can be used as a CI/CD gate.

Invalid configuration exits with code `2`.

## Recovery regression

Reaching consistency once is not enough.

ERPChaos records `regressed_after_recovery = true` when:

1. all recovery invariants pass at a checkpoint, so TTBC is reached; and
2. later recovery events make the final state inconsistent again.

This detects transient or over-compensating recovery logic that a simple final-state or first-success check could miss.

```text
Failure
  |
  +-- reversal #1 --> RECOVERED
  |                    TTBC = 1
  |
  +-- reversal #2 --> PARTIALLY_RECOVERED
                       regressed_after_recovery = true
```

## CLI

Run the successful property-sale recovery example:

```bash
erpchaos recovery run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-recovery.brc.yaml \
  examples/real-estate/payment-recovered.recovery.yaml
```

The command displays each recovery checkpoint, its Recovery Reliability Score, the final recovery classification, TTBC, and whether recovery later regressed.

A recovery experiment is valid only when the chaos phase first breaks the original business contract. If the chaos scenario does not create a business failure, ERPChaos rejects the recovery experiment instead of pretending that compensation was required.

## CI contract

A CI pipeline should test at least two paths:

1. a known business failure followed by valid compensation must return `RECOVERED` and exit `0`;
2. incomplete, excessive, or regressing compensation must remain a business failure and exit `1`.

The ERPChaos repository runs both recovered and regression paths on Python 3.11 and 3.12.

## Safety model

Business Recovery Engineering follows the same safety boundary as the rest of ERPChaos:

- deterministic fixtures only;
- no production mutation;
- no stored ERP credentials;
- no timing-dependent threads or sleeps;
- no LLM or AI service decides pass/fail;
- scores derive only from explicit contract invariants;
- recovery behavior must be reproducible in CI.

For production-derived incidents, sanitize them first using the workflow in [`INCIDENT_REPLAY.md`](INCIDENT_REPLAY.md), then use the resulting safe event stream as deterministic replay input.
