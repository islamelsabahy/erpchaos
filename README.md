# ERPChaos

> **Your infrastructure can be green while your business is broken.**

ERPChaos is an open-source experiment in **Business Transaction Chaos Engineering**: deterministic testing of ERP and business workflows under duplicate events, dropped events, delayed processing, out-of-order delivery, partial failures, retries, competing transactions, and failed recovery paths that can leave technically healthy systems in financially or operationally invalid states.

ERPChaos is not an AI chatbot, a generic ERP test runner, or a security scanner. Its core idea is to treat **business invariants as executable reliability contracts**, business event streams as reproducible chaos experiments, and recovery behavior as something that can be measured and gated in CI.

## Why ERPChaos?

Traditional chaos engineering asks whether infrastructure survives failure.

ERPChaos asks three different questions:

1. **Did the business transaction remain correct when failure happened?**
2. **If it broke, did the compensating business flow actually recover it?**
3. **Did the recovered state stay consistent, or did recovery regress later?**

Examples:

- Can two users reserve the same property at the same time?
- Can a retry create duplicate payments or commissions?
- Can payment happen before finance approval while every event still exists?
- Can a sold unit accidentally return to available state?
- Can out-of-order events corrupt a workflow while every service still reports healthy?
- Can a real incident be converted into a safe deterministic regression fixture without committing PII or credentials?
- Can a duplicate payment be compensated correctly, and can ERPChaos prove the recovery stays stable?

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

Supported chaos primitives:

- `duplicate_event`
- `drop_event`
- `delay_event`
- `reorder_event`
- `partial_failure`

### Event-history projection

After replay, ERPChaos converts the mutated event stream into deterministic BRC-readable state. Each normalized event type exposes occurrence count and first/last positions.

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

### Business Recovery Engineering

ERPChaos can continue after a known chaos-induced business failure and evaluate ordered compensating events against a dedicated `RecoveryContract`.

```text
Baseline EventStream
        |
        v
     Chaos
        |
        v
Business Failure
        |
        v
Recovery Events
        |
        +--> checkpoint -> Recovery Contract -> RRS
        +--> checkpoint -> Recovery Contract -> RRS
        |
        v
Final Recovery Classification
```

Recovery is deterministic and fixture-based. ERPChaos does not execute compensating writes against a production ERP.

Recovery results include:

- **Recovery Reliability Score (RRS)** — severity-weighted recovery score from `0` to `100`.
- **Time to Business Consistency (TTBC)** — first deterministic recovery-event step where all recovery invariants pass.
- **Recovery status** — `RECOVERED`, `PARTIALLY_RECOVERED`, or `UNRECOVERED`.
- **Recovery regression detection** — identifies a transaction that reached consistency and then became inconsistent again because of later compensation.

Example:

```bash
erpchaos recovery run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-recovery.brc.yaml \
  examples/real-estate/payment-recovered.recovery.yaml
```

See [`docs/RECOVERY_ENGINEERING.md`](docs/RECOVERY_ENGINEERING.md) for the full recovery model and CI contract.

### Deterministic concurrency

ERPChaos can model multiple transactions competing for the same business resource. Concurrency schedules are explicit rather than random, so a race can be replayed exactly in CI.

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

If both transactions emit `reservation.succeeded` while `max_successes` is `1`, ERPChaos reports a **Business Race Condition** and fails with exit code `1`.

### Safe Odoo read adapter

The first ERP-specific adapter boundary translates previously exported Odoo-like activity into the same vendor-neutral `EventStream` format used by the core engine.

The current adapter is deliberately constrained:

- `read_only` must be `true`
- only `demo`, `test`, and `staging` environments are accepted
- credentials are not part of the configuration schema
- credentials embedded in URLs are rejected
- query strings and fragments in adapter URLs are rejected
- payload fields are explicit allowlists
- password, secret, token, API-key, credential, and session fields are rejected
- transaction and activity identifiers are deterministically hashed before export
- unmapped source activity fails closed instead of being silently dropped
- the adapter does not contact Odoo; it translates an already exported fixture

```bash
erpchaos adapter odoo translate \
  examples/odoo/property-sale.export.yaml \
  --output /tmp/odoo-event-streams.yaml
```

### Safe incident replay

ERPChaos can turn a locally captured incident into a replay-safe `EventStream` while preserving event order and correlation.

Safety rules:

- transaction and event IDs are always HMAC-pseudonymized
- the pseudonymization key is runtime-only and never belongs in policy YAML
- payload fields are dropped by default
- surviving fields require explicit `keep`, `tokenize`, `redact`, or `drop` rules
- credential fields are always dropped and cannot be configured for another action
- obvious PII cannot be kept in raw form
- generated fixtures receive a second fail-closed validation pass

```bash
export ERPCHAOS_PSEUDONYM_KEY='replace-with-runtime-secret-key'

erpchaos incident sanitize \
  examples/incidents/property-sale.raw.synthetic.yaml \
  examples/incidents/property-sale.policy.yaml \
  --output /tmp/property-sale.safe.yaml

erpchaos incident validate /tmp/property-sale.safe.yaml
```

The repository raw incident example is synthetic only. Real raw incident captures should remain outside the repository. See [`docs/INCIDENT_REPLAY.md`](docs/INCIDENT_REPLAY.md).

### GitHub Action

ERPChaos can also be consumed directly as a composite GitHub Action. A known-good immutable reference from the v0.8 mainline is:

```yaml
- uses: islamelsabahy/erpchaos@a297e940dd6255dd3148838bfa78e980329dccb1
  with:
    mode: experiment
    contract: reliability/property-sale.events.brc.yaml
    scenario: reliability/duplicate-payment.scenario.yaml
    stream: reliability/property-sale.events.yaml
```

The Action preserves the CLI exit-code contract and publishes `status` plus `exit-code` outputs and a Job Summary. See [`docs/GITHUB_ACTION.md`](docs/GITHUB_ACTION.md).

## Experiment shapes

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

A recovery experiment extends the loop after a business failure:

```text
Event Stream -> Chaos -> Failed Projection -> Recovery Event 1 -> Recovery Contract
                                                    |
                                                    v
                                                   RRS
                                                    |
                                   Recovery Event N -> Final Status
                                                    |
                                      TTBC + Regression Detection
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

A safe incident workflow creates deterministic regression input:

```text
Local Raw Incident -> Sanitization Policy -> HMAC Pseudonyms -> Leak Validation
                                                               |
                                                               v
                                                     Safe EventStream Fixture
                                                               |
                                                  Replay / Chaos / Recovery
```

### Deterministic by design

LLMs may eventually help generate scenarios or explain failures, but **AI never decides pass/fail or mutates production systems**. Reliability checks, replay, recovery evaluation, concurrency experiments, ERP translation, and incident sanitization remain deterministic and suitable for CI/CD.

## Current alpha

`v0.9.0-alpha` development provides:

- Business Reliability Contract model
- deterministic invariant evaluator
- literal and cross-path ordering operators
- severity-weighted Business Reliability Score
- vendor-neutral business event streams
- five deterministic fault injection primitives
- ordered transaction replay engine
- deterministic event-history projection
- end-to-end post-chaos BRC evaluation
- deterministic Business Recovery Engineering
- Recovery Contracts and ordered recovery scenarios
- Recovery Reliability Score (RRS)
- deterministic Time to Business Consistency (TTBC)
- `RECOVERED`, `PARTIALLY_RECOVERED`, and `UNRECOVERED` classification
- recovery-regression detection after temporary consistency
- deterministic competing-transaction interleaving
- shared-resource exclusivity evaluation
- Business Race Condition detection
- ERP adapter protocol boundary
- safe offline Odoo export adapter
- deterministic source identifier hashing
- allowlist-only Odoo payload translation
- reusable composite GitHub Action with `verify`, `chaos`, and `experiment` modes
- stable GitHub Action status and exit-code outputs
- deterministic incident sanitization policies
- runtime-keyed HMAC pseudonymization
- default-drop payload handling
- forced credential-field removal
- obvious PII leak detection and replay-fixture validation
- CLI verification, replay, experiment, recovery, concurrency, adapter, and incident commands
- real-estate, synthetic Odoo, synthetic incident, and recovery examples
- automated tests and CI across Python 3.11 and 3.12

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

Replay a duplicate-payment fault:

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

Run a deterministic recovery experiment after the duplicate-payment failure:

```bash
erpchaos recovery run \
  examples/real-estate/property-sale.events.brc.yaml \
  examples/real-estate/duplicate-payment.scenario.yaml \
  examples/real-estate/property-sale.events.yaml \
  examples/real-estate/payment-recovery.brc.yaml \
  examples/real-estate/payment-recovered.recovery.yaml
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
erpchaos concurrency run examples/real-estate/single-winner.concurrent.yaml
```

Detect a double-reservation race:

```bash
erpchaos concurrency run examples/real-estate/double-reservation.concurrent.yaml
```

Translate a safe synthetic Odoo export:

```bash
erpchaos adapter odoo translate \
  examples/odoo/property-sale.export.yaml \
  --output /tmp/odoo-event-streams.yaml
```

Sanitize and validate a synthetic incident:

```bash
export ERPCHAOS_PSEUDONYM_KEY='synthetic-local-key-at-least-16-chars'
erpchaos incident sanitize \
  examples/incidents/property-sale.raw.synthetic.yaml \
  examples/incidents/property-sale.policy.yaml \
  --output /tmp/property-sale.safe.yaml
erpchaos incident validate /tmp/property-sale.safe.yaml
```

Business-correctness and unrecovered/partially recovered business failures use exit code `1`. Invalid configuration, unsafe incident input, and adapter input use exit code `2`.

## Architecture direction

The core stays vendor-neutral:

```text
                         Business Reliability Contract
                                  |
                                  v
ERP Event Stream -> Chaos -> Replay -> Projection -> Invariant Engine -> BRS
                     |
                     +--> known failed transaction
                                  |
                                  v
                         Recovery Scenario
                                  |
                         Recovery Checkpoints
                                  |
                                  v
                         Recovery Contract
                                  |
                    RRS + TTBC + Regression Check

Competing Event Streams -> Deterministic Scheduler -> Exclusivity Engine -> BRS
                                  |
                           Shared Resource

Odoo Export -> Safe Odoo Read Adapter -> Vendor-neutral Event Streams
                     |
              allowlist + hashing

Raw Incident -> Sanitization Policy -> HMAC Pseudonyms -> Safe EventStream
                     |                       |
              default drop             leak validation

                     ERP Adapter Boundary
              Odoo / REST / Webhook / future adapters
```

Vendor-specific integrations must remain behind the adapter boundary. Any future live connector should begin read-only, use runtime-only authentication, and explicitly refuse destructive production execution.

## Direction

Planned work includes:

- richer shared-resource and history-aware invariants
- compensation-aware projections beyond event counts
- runtime-authenticated read-only Odoo extraction
- generic REST and webhook adapters
- BRC and Recovery Contract schema versioning
- richer PII detection hooks and organization-specific sanitization policies
- OpenTelemetry correlation
- machine-readable experiment reports for external CI policy engines

## Project principles

1. Business correctness is a reliability concern.
2. Deterministic verification comes before AI assistance.
3. Infrastructure health does not imply transaction integrity.
4. Recovery is not complete until explicit business invariants pass.
5. Reaching consistency temporarily is not the same as stable recovery.
6. Raw production incident data must stay outside the repository.
7. Production-derived fixtures must be sanitized and validated before replay.
8. Vendor-specific ERP behavior belongs behind adapters.
9. Every new failure mode and recovery path should be reproducible in CI.
10. Chaos execution must default to safe, non-production environments.
11. Concurrency schedules must be reproducible rather than timing-dependent.
12. ERP adapters must fail closed and must not store credentials in fixtures.
13. Pseudonymization keys must be runtime-only secrets, never repository configuration.
14. Recovery events are fixtures, never implicit production mutations.

## Status

ERPChaos is an early-stage open-source project and the specification is expected to evolve before `1.0`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0.
