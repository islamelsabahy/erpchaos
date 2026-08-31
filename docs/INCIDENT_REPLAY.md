# Safe Incident Replay

ERPChaos can convert a production-derived business event stream into a deterministic replay fixture without preserving raw transaction identifiers, event identifiers, obvious PII, or credential fields.

## Safety model

Incident sanitization is fail-closed by design:

- transaction IDs and event IDs are always converted to HMAC-based pseudonyms
- the pseudonymization key is runtime-only and is never part of the policy schema
- payload fields are dropped by default
- every field that must survive sanitization needs an explicit `keep`, `tokenize`, `redact`, or `drop` rule
- credential/secret fields are always dropped and cannot be configured for another action
- `keep` is rejected when ERPChaos detects an obvious PII field or value
- a second validation pass checks the generated fixture for credential fields and obvious PII leaks
- event order and repeated-reference correlation are preserved deterministically

HMAC pseudonymization is not the same as irreversible anonymization. Treat the runtime key as sensitive and rotate it according to your incident-handling policy.

## Recommended workflow

1. Capture the source incident outside the repository.
2. Create a sanitization policy in the repository using only field names and transformation rules.
3. Supply `ERPCHAOS_PSEUDONYM_KEY` at runtime from a local secret store or CI secret.
4. Sanitize to a temporary location outside the repository.
5. Run `erpchaos incident validate` on the generated fixture.
6. Review the sanitized YAML before copying it into `examples/` or a test fixture directory.
7. Commit only the validated sanitized fixture, never the raw production capture.

## Policy example

```yaml
schema: erpchaos.incident-sanitization-policy.v1
name: Property sale incident
default_action: drop
pii_detection: true
rules:
  - path: customer_email
    action: tokenize
  - path: customer_phone
    action: redact
  - path: unit_ref
    action: tokenize
  - path: state
    action: keep
```

Actions:

- `keep`: preserve a non-sensitive scalar value
- `tokenize`: replace the value with a stable HMAC pseudonym so repeated references still correlate
- `redact`: replace the value with `[REDACTED]`
- `drop`: remove the field

## CLI

The repository includes a synthetic raw fixture for demonstration only. It contains fake `.test` email addresses and a fake token value.

```bash
export ERPCHAOS_PSEUDONYM_KEY='replace-with-runtime-secret-key'

erpchaos incident sanitize \
  examples/incidents/property-sale.raw.synthetic.yaml \
  examples/incidents/property-sale.policy.yaml \
  --output /tmp/property-sale.safe.yaml

erpchaos incident validate /tmp/property-sale.safe.yaml
```

The generated file is a normal ERPChaos `EventStream`, so it can be passed directly to replay and experiment commands.

## CI guidance

Do not commit a real pseudonymization key. Use a CI secret for production-derived incident workflows. Synthetic repository smoke tests may use a clearly test-only key because no real identifying data is present.

A safe CI gate should validate that:

- the sanitization command succeeds
- the resulting file passes `incident validate`
- known synthetic raw identifiers are absent from the output
- the generated YAML still validates as an ERPChaos `EventStream`
