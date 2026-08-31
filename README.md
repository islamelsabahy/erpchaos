# ERPChaos

> **Your infrastructure can be green while your business is broken.**

ERPChaos is an open-source experiment in **Business Transaction Chaos Engineering**: deterministic testing of ERP and business workflows under duplicate events, concurrency, partial failure, delayed approvals, integration outages, and other failure modes that can leave technically healthy systems in financially or operationally invalid states.

ERPChaos is not an AI chatbot, a generic ERP test runner, or a security scanner. Its core idea is to treat **business invariants as executable reliability contracts**.

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

### Deterministic by design

LLMs may eventually help generate scenarios or explain failures, but **AI never decides pass/fail**. Reliability checks stay deterministic, reproducible, and suitable for CI/CD.

## Current alpha

`v0.1.0-alpha` currently provides:

- Business Reliability Contract model
- Deterministic invariant evaluator
- Severity-weighted reliability score
- CLI verification command
- Real-estate transaction example
- Automated tests
- GitHub Actions CI

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

The second command exits non-zero because critical invariants fail, making the result usable as a CI/CD deployment gate.

## Direction

Planned work includes:

- fault injection primitives
- transaction replay
- concurrency experiments
- duplicate/out-of-order event simulation
- generic REST and webhook adapters
- Odoo adapter
- BRC schema versioning
- recovery scoring
- incident replay fixtures
- GitHub Action packaging
- OpenTelemetry correlation

## Project principles

1. Business correctness is a reliability concern.
2. Deterministic verification comes before AI assistance.
3. Infrastructure health does not imply transaction integrity.
4. Production data must be anonymized before replay.
5. Vendor-specific ERP behavior belongs behind adapters.
6. Every new failure mode should be reproducible in CI.

## Status

ERPChaos is an early-stage open-source project and the specification is expected to evolve before `1.0`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0.
