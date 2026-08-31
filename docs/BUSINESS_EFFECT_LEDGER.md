# Business Effect Ledger

The ERPChaos **Business Effect Ledger (BEL)** projects an ordered business event stream into deterministic net business effects.

Event history answers **what happened**. The Business Effect Ledger answers **what business effect remains**.

For example, a duplicate payment callback followed by one compensation can contain:

```text
payment.received
payment.received
payment.reversed
```

The raw history correctly reports two receipt events and one reversal event. The effect ledger additionally reports that exactly one effective payment remains.

## Effect map

An effect map is vendor-neutral YAML that assigns signed integer contributions to business event types.

```yaml
schema: erpchaos.effect-map.v1
name: Property sale business effects
effects:
  payment:
    contributions:
      payment.received: 1
      payment.reversed: -1
  commission:
    contributions:
      commission.created: 1
      commission.voided: -1
```

In v0.10, contributions are integers only. ERPChaos deliberately avoids floating-point financial arithmetic in this projection layer.

An effect map describes semantic state transitions, not currency amounts. A contribution of `1` means one active business effect; `-1` means one compensating effect.

Zero contributions are rejected because they provide no semantic value and can hide configuration mistakes.

## Ledger projection

For every configured effect, ERPChaos calculates:

| Field | Meaning |
| --- | --- |
| `balance` | Final net effect after all mapped events |
| `min_balance` | Lowest balance reached at any event step, including the initial zero state |
| `max_balance` | Highest balance reached at any event step |
| `contribution_count` | Number of events that changed this effect |
| `ever_negative` | Whether the effect balance dropped below zero at any point |

Example:

```yaml
effects:
  payment:
    balance: 1
    min_balance: 0
    max_balance: 2
    contribution_count: 3
    ever_negative: false
```

This means the transaction temporarily contained two effective payments, was compensated once, and ended with one effective payment without ever entering a negative payment state.

## Why final balance is not enough

Consider this sequence:

```text
payment.reversed   -> balance -1
payment.received   -> balance  0
```

The final balance is zero, but the history contains an orphan reversal that existed before any effective payment.

ERPChaos exposes this through:

```yaml
balance: 0
min_balance: -1
ever_negative: true
```

A BRC can therefore reject the transaction even when the final net balance looks harmless.

## Over-compensation

A transaction can also recover correctly and then be compensated again:

```text
payment.received   -> 1
payment.received   -> 2
payment.reversed   -> 1   # recovered
payment.reversed   -> 0   # recovery regressed
```

When used with Business Recovery Engineering, the first reversal can establish TTBC while the second reversal causes the final Recovery Contract to fail. ERPChaos then reports `regressed_after_recovery = true`.

This combines temporal recovery semantics with net business-effect semantics.

## Contract paths

BEL output is merged with the existing event-history projection when an effect map is supplied.

Contracts can therefore evaluate both kinds of evidence in one deterministic state:

```yaml
invariants:
  - name: one-effective-payment
    path: effects.payment.balance
    operator: equals
    expected: 1
    severity: critical

  - name: payment-never-negative
    path: effects.payment.ever_negative
    operator: equals
    expected: false
    severity: critical

  - name: reversal-after-payment
    path: history.types.payment_reversed.first_position
    operator: after
    expected_path: history.types.payment_received.last_position
    severity: critical
```

The first two invariants verify business effect. The third verifies event ordering.

## CLI

Project a ledger directly:

```bash
erpchaos effect project \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/property-sale.effects.yaml
```

Run an effect-aware chaos experiment:

```bash
erpchaos experiment run \
  examples/real-estate/payment-effect.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  --effect-map examples/real-estate/property-sale.effects.yaml
```

Run compensation-aware recovery:

```bash
erpchaos recovery run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-effect-recovery.brc.yaml \
  examples/real-estate/payment-recovered.recovery.yaml \
  --effect-map examples/real-estate/property-sale.effects.yaml
```

The `--effect-map` option is optional. Existing history-only experiments and recovery workflows remain valid without it.

## Determinism and safety

The BEL follows the same project principles as the ERPChaos core:

- ordered event input only;
- deterministic integer arithmetic;
- no wall-clock timing;
- no production mutation;
- no ERP credentials;
- no AI or LLM participates in projection or pass/fail;
- identical event streams and effect maps produce identical output.

## Current boundary

v0.10 intentionally models **effect cardinality**, not monetary value.

It can express ideas such as:

- one effective payment remains;
- no active commission remains;
- two reservations temporarily existed;
- a compensation occurred before its originating effect;
- recovery over-compensated a transaction.

Future versions may add typed and value-aware effects, but those should use explicit deterministic numeric semantics rather than floating-point shortcuts.
