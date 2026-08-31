# ERPChaos

> **Your infrastructure can be green while your business is broken.**

ERPChaos is an open-source experiment in **Business Transaction Chaos Engineering**: deterministic testing of ERP and business workflows under duplicate events, dropped events, delayed processing, out-of-order delivery, partial failures, retries, and other failure modes that can leave technically healthy systems in financially or operationally invalid states.

ERPChaos is not an AI chatbot, a generic ERP test runner, or a security scanner. Its core idea is to treat **business invariants as executable reliability contracts** and business event streams as reproducible chaos experiments.

## Why ERPChaos?

Traditional chaos engineering asks whether infrastructure survives failure.

ERPChaos asks whether the **business transaction remains correct** when failure happens.

Examples:

- Can one property be sold twice during concurrent reservations?
- Can a retry create duplicate payments or commissions?
- Can a sold unit accidentally return to available state?
- Can a transaction complete before finance approval?
- Can out-of-order events corrupt a workflow while every service still reports healthy?

## Core concepts

### Business Reliability Contract (BRC)

A BRC defines invariants that must remain true for a business transaction.

```yaml
name: Property Sale Reliability Contract
transaction: property-sale
invariants:
  - name: payment-idempotency
    path: payment.posted_records
    operator: equals
    expected: 1
    severity: critical
```

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

### Deterministic by design

LLMs may eventually help generate scenarios or explain failures, but **AI never decides pass/fail or mutates production systems**. Reliability checks and chaos experiments stay deterministic, reproducible, and suitable for CI/CD.

## Current alpha

`v0.2.0-alpha` provides:

- Business Reliability Contract model
- Deterministic invariant evaluator
- Severity-weighted reliability score
- Vendor-neutral business event streams
- Five deterministic fault injection primitives
- Ordered transaction replay engine
- CLI verification and chaos replay commands
- Real-estate transaction examples
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

Test a deliberately broken state:

```bash
erpchaos verify \
  examples/real-estate/property-sale.brc.yaml \
  examples/real-estate/duplicate-payment-state.yaml
```

Run a deterministic duplicate-payment chaos experiment:

```bash
erpchaos chaos run \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml
```

The `verify` command exits non-zero when business invariants fail, making BRC verification usable as a CI/CD deployment gate.

## Architecture direction

The core stays vendor-neutral:

```text
Business Reliability Contracts
            |
      Invariant Engine
            |
Event Stream -> Chaos Engine -> Mutated Event Stream
            |         |
         Replay     Faults
            |
       ERP Adapters
   Odoo / REST / Webhook / ...
```

Vendor-specific ERP integrations will translate external activity into ERPChaos event streams and apply replay only in explicitly controlled test environments.

## Direction

Planned work includes:

- state projection from replayed event streams
- concurrency experiments
- idempotency assertions over event histories
- generic REST and webhook adapters
- Odoo adapter
- BRC schema versioning
- recovery scoring
- incident replay fixtures
- GitHub Action packaging
- OpenTelemetry correlation
- anonymization tooling for production-derived fixtures

## Project principles

1. Business correctness is a reliability concern.
2. Deterministic verification comes before AI assistance.
3. Infrastructure health does not imply transaction integrity.
4. Production data must be anonymized before replay.
5. Vendor-specific ERP behavior belongs behind adapters.
6. Every new failure mode should be reproducible in CI.
7. Chaos execution must default to safe, non-production environments.

## Status

ERPChaos is an early-stage open-source project and the specification is expected to evolve before `1.0`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0.
