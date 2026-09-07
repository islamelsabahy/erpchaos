# Business Transaction Trace Correlation

ERPChaos v0.18 adds deterministic, vendor-neutral transaction trace correlation for sanitized offline exports.

The goal is not infrastructure tracing. The goal is to reconstruct a business transaction path, detect broken correlation, and safely project a valid trace into the existing ERPChaos `EventStream` model.

## Canonical schema

Transaction traces use:

```yaml
schema: erpchaos.transaction-trace.v1
trace_id: trace-001
transaction_id: sale-001
events:
  - event_id: reservation-001
    event_type: reservation.created
    transaction_id: sale-001
    source_system: crm
    sequence: 10
    payload:
      unit_ref: UNIT-DEMO-203
  - event_id: finance-001
    event_type: finance.approved
    transaction_id: sale-001
    source_system: finance
    sequence: 20
    parent_event_id: reservation-001
    causation_event_id: reservation-001
```

Each event has explicit business identity and correlation metadata:

- `event_id`: stable event/span identity inside the trace
- `event_type`: vendor-neutral business event type
- `transaction_id`: business transaction identity
- `source_system`: source service/application/system
- `sequence`: explicit deterministic sibling/order tie-breaker
- `parent_event_id`: structural parent correlation
- `causation_event_id`: causal relationship when known
- `timestamp`: optional diagnostic metadata only
- `payload`: sanitized business payload

Timestamps are never used as the sole causal truth.

## Diagnostics

Validation produces `erpchaos.trace-diagnostics.v1` with stable issue IDs and deterministic ordering.

Current fail-closed diagnostics include:

- `TRACE_DUPLICATE_EVENT_ID`
- `TRACE_MISSING_PARENT`
- `TRACE_MISSING_CAUSATION`
- `TRACE_AMBIGUOUS_PARENT`
- `TRACE_AMBIGUOUS_CAUSATION`
- `TRACE_CROSS_TRANSACTION`
- `TRACE_CAUSAL_CYCLE`

A trace with any of these issues is not projected into an ERPChaos `EventStream`.

ERPChaos never silently invents a missing parent or causation edge.

## Deterministic ordering

Valid traces are ordered with a deterministic topological traversal:

1. explicit parent and causation references define causal edges;
2. only zero-indegree events are eligible at each step;
3. `sequence` and then `event_id` deterministically order independent eligible events;
4. cycles fail closed instead of being broken heuristically.

## CLI

Inspect a canonical trace:

```bash
erpchaos trace inspect examples/traces/property-sale.trace.yaml
erpchaos trace inspect examples/traces/property-sale.trace.yaml --json
```

Validate correlation and emit deterministic diagnostics:

```bash
erpchaos trace validate examples/traces/property-sale.trace.yaml
erpchaos trace validate examples/traces/property-sale.trace.yaml --json
```

Project a valid trace into an ERPChaos `EventStream`:

```bash
erpchaos trace project \
  examples/traces/property-sale.trace.yaml \
  --output /tmp/property-sale.events.yaml \
  --diagnostics /tmp/property-sale.trace-diagnostics.json
```

Translate a sanitized offline OTLP JSON export:

```bash
erpchaos trace from-otel \
  examples/traces/property-sale.otel.json \
  --output /tmp/property-sale.trace.yaml \
  --diagnostics /tmp/property-sale.otel-diagnostics.json
```

## Exit semantics

Trace commands use:

- `0`: valid trace / successful projection or translation
- `1`: semantic correlation failure or ambiguous trace
- `2`: invalid input, schema, JSON/YAML, or unsupported adapter input

## Offline OpenTelemetry adapter

OpenTelemetry is an adapter only. The ERPChaos core does not depend on OpenTelemetry packages, collectors, agents, exporters, backends, or network services.

The adapter accepts OTLP JSON containing exactly one trace and exactly one business transaction.

Each resource must provide:

```text
service.name
```

Each span must provide explicit ERPChaos attributes:

```text
erpchaos.transaction_id
erpchaos.event_type
erpchaos.sequence
```

Optional correlation:

```text
erpchaos.causation_span_id
```

Only payload attributes under this namespace are copied into the ERPChaos business payload:

```text
erpchaos.payload.*
```

Other span attributes are ignored by the adapter. This prevents arbitrary telemetry metadata, headers, tokens, and unrelated attributes from being copied into ERPChaos fixtures by default.

Supported OTLP scalar attribute value types are `stringValue`, `intValue`, `boolValue`, and `doubleValue`.

## Safety contract

Transaction trace ingestion is intentionally offline and read-only:

- no collector connections
- no telemetry backend queries
- no agent deployment
- no credentials
- no production mutation
- no AI/LLM in validation, diagnostics, ordering, or projection
- sanitized synthetic fixtures only in the public repository

Sanitize production-derived exports before ERPChaos ingestion. The adapter does not make raw telemetry safe automatically.

## Determinism

The v0.18 workflow verifies that Python 3.11 and 3.12 produce byte-identical:

- trace diagnostics JSON
- projected EventStream YAML
- canonical trace YAML generated from the synthetic OTLP fixture

This keeps transaction reconstruction suitable for CI policy gates and reproducible evidence pipelines.
