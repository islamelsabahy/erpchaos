# ERPChaos

> **Your infrastructure can be green while your business is broken.**

ERPChaos is an open-source experiment in **Business Transaction Chaos Engineering**: deterministic testing of ERP and business workflows under duplicate events, dropped events, delayed processing, out-of-order delivery, partial failures, retries, and competing transactions that can leave technically healthy systems in financially or operationally invalid states.

ERPChaos is not an AI chatbot, a generic ERP test runner, or a security scanner. Its core idea is to treat **business invariants as executable reliability contracts** and business event streams as reproducible chaos experiments.

## Why ERPChaos?

Traditional chaos engineering asks whether infrastructure survives failure.

ERPChaos asks whether the **business transaction remains correct** when failure happens.

Examples:

- Can two users reserve the same property at the same time?
- Can a retry create duplicate payments or commissions?
- Can payment happen before finance approval while every event still exists?
- Can a sold unit accidentally return to available state?
- Can out-of-order events corrupt a workflow while every service still reports healthy?

## Core concepts

### Business Reliability Contract (BRC)

A BRC defines invariants that must remain true for a business transaction.

```yaml
name: Property Sale Event Reliability Contract
transaction: property-sale-event-history
invariants:
  - name: payment-idempotency
    path: history.types.payment_received.count
    operator: equals
    expected: 1
    severity: critical

  - name: finance-before-payment
    path: history.types.finance_approved.first_position
    operator: before
    expected_path: history.types.payment_received.first_position
    severity: critical
```

Literal operators currently include `equals`, `not_equals`, `lte`, and `gte`. Cross-path ordering operators include `before` and `after`.

### Business Reliability Score (BRS)

ERPChaos evaluates invariant results using severity-weighted scoring and returns a score from `0` to `100`.

### Deterministic transaction replay

ERPChaos represents a transaction as an ordered, vendor-neutral event stream and applies declared faults in a deterministic sequence. The same input stream and scenario always produce the same mutated timeline.

Supported chaos primitives in the current alpha:

- `duplicate_event`
- `drop_event`
- `delay_event`
- `reorder_event`
- `partial_failure`

### Event-history projection

After replay, ERPChaos converts the mutated event stream into deterministic BRC-readable state. Each normalized event type exposes its occurrence count and first/last positions.

A duplicated `payment.received` event becomes:

```yaml
history:
  types:
    payment_received:
      count: 2
      first_position: 3
      last_position: 4
```

This lets a BRC evaluate the **result of chaos**, not only a static fixture.

### Cross-event ordering

Counts alone are not enough. A transaction can contain all required events and still be invalid because they happened in the wrong order.

```yaml
- name: finance-before-payment
  path: history.types.finance_approved.first_position
  operator: before
  expected_path: history.types.payment_received.first_position
  severity: critical
```

A `reorder_event` fault can move payment ahead of finance approval while preserving every event count. ERPChaos detects that semantic failure through the ordering invariant.

### Deterministic concurrency

ERPChaos can also model multiple transactions competing for the same business resource. Concurrency schedules are explicit rather than random, so a race can be replayed exactly in CI.

```yaml
name: Double reservation race
resource_key: unit:A-203
success_event_type: reservation.succeeded
max_successes: 1
streams:
  - transaction_id: reservation-A
    events: [...]
  - transaction_id: reservation-B
    events: [...]
schedule:
  - reservation-A
  - reservation-B
  - reservation-A
  - reservation-B
```

Each schedule entry consumes the next event from that transaction. If both transactions emit `reservation.succeeded` while `max_successes` is `1`, ERPChaos reports a **Business Race Condition** and fails with exit code `1`.

### Chaos experiment

A standard chaos experiment closes the single-transaction reliability loop:

```text
Event Stream
    |
Fault Injection
    |
Deterministic Replay
    |
History Projection
    |
BRC Evaluation
    |
Business Reliability Score
```

A concurrency experiment evaluates a shared-resource race:

```text
Transaction A ----\
                   > Deterministic Interleaving -> Exclusivity Check -> BRS
Transaction B ----/
                           |
                     Shared Resource
                       unit:A-203
```

### Deterministic by design

LLMs may eventually help generate scenarios or explain failures, but **AI never decides pass/fail or mutates production systems**. Reliability checks, replay, and concurrency experiments stay deterministic, reproducible, and suitable for CI/CD.

## Current alpha

`v0.5.0-alpha` provides:

- Business Reliability Contract model
- Deterministic invariant evaluator
- Literal and cross-path ordering operators
- Severity-weighted reliability score
- Vendor-neutral business event streams
- Five deterministic fault injection primitives
- Ordered transaction replay engine
- Deterministic event-history projection
- End-to-end post-chaos BRC evaluation
- Deterministic competing-transaction interleaving
- Shared-resource exclusivity evaluation
- Business Race Condition detection
- CLI verification, replay, experiment, and concurrency commands
- Real-estate duplicate-payment, early-payment, and double-reservation scenarios
- Automated tests
- GitHub Actions CI across Python 3.11 and 3.12

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
```

Verify a healthy property-sale transaction:

```bash
erpchaos verify \
  examples/real-estate/property-sale.brc.yaml \
  examples/real-estate/healthy-state.yaml
```

Replay a duplicate-payment fault without evaluating business correctness:

```bash
erpchaos chaos run \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml
```

Run the full duplicate-payment experiment:

```bash
erpchaos experiment run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml
```

Run an ordering experiment where payment is moved ahead of finance approval:

```bash
erpchaos experiment run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/early-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml
```

Run a safe single-winner reservation race:

```bash
erpchaos concurrency run \
  examples/real-estate/single-winner.concurrent.yaml
```

Detect a double-reservation race:

```bash
erpchaos concurrency run \
  examples/real-estate/double-reservation.concurrent.yaml
```

The double-reservation command exits with code `1` because two competing transactions succeeded against one resource where only one success is allowed. Invalid configuration uses exit code `2`.

## Architecture direction

The core stays vendor-neutral:

```text
                     Business Reliability Contract
                              |
                              v
ERP Event Stream -> Chaos -> Replay -> Projection -> Invariant Engine
                     |                         |             |
                   Faults                  State Model      BRS

Competing Event Streams -> Deterministic Scheduler -> Exclusivity Engine
                                  |                    |
                           Shared Resource             BRS

                     ERP Adapter Boundary
              Odoo / REST / Webhook / future adapters
```

Vendor-specific ERP integrations will translate external activity into ERPChaos event streams and execute only inside explicitly controlled test environments.

## Direction

Planned work includes:

- richer shared-resource and history-aware invariants
- generic REST and webhook adapters
- safe Odoo adapter
- BRC schema versioning
- recovery scoring
- anonymized incident replay fixtures
- GitHub Action packaging
- OpenTelemetry correlation

## Project principles

1. Business correctness is a reliability concern.
2. Deterministic verification comes before AI assistance.
3. Infrastructure health does not imply transaction integrity.
4. Production data must be anonymized before replay.
5. Vendor-specific ERP behavior belongs behind adapters.
6. Every new failure mode should be reproducible in CI.
7. Chaos execution must default to safe, non-production environments.
8. Concurrency schedules must be reproducible rather than timing-dependent.

## Status

ERPChaos is an early-stage open-source project and the specification is expected to evolve before `1.0`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0.
