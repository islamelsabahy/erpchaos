# Business Reliability Baselines

ERPChaos v0.17 adds deterministic reliability baselines for legacy ERP estates that already contain known business-reliability debt.

A baseline is not a wildcard ignore list. It records stable finding identities and their observed severities. Current findings are classified as:

- `KNOWN` — the same fingerprint exists at the same or lower severity.
- `NEW` — the fingerprint was not present in the baseline.
- `RESOLVED` — a baseline fingerprint is no longer present.
- `REGRESSED` — the same fingerprint is present at a higher severity.

## Stable fingerprints

A finding fingerprint is SHA-256 over the stable rule and invariant identity:

```text
rule_id
transaction
invariant_name
invariant_path
```

Severity and message text are deliberately excluded so severity increases can be classified as `REGRESSED` instead of appearing as unrelated new findings.

Baseline documents do not store raw transaction payloads, actual values, expected values, credentials, or customer data.

## Capture a baseline

First generate canonical findings, then capture them:

```bash
erpchaos policy evaluate \
  examples/real-estate/property-sale.brc.yaml \
  examples/real-estate/policy-failing-state.synthetic.yaml \
  examples/policy/strict-business-gate.yaml \
  --findings-output findings.json

erpchaos baseline capture findings.json \
  --name legacy-property-sale \
  --output baseline.json
```

`policy evaluate` can return exit code `1` while still writing the findings artifact. That is expected when the synthetic state violates policy.

## Compare current findings

```bash
erpchaos baseline compare \
  baseline.json \
  current-findings.json \
  --evaluation-date 2026-09-07 \
  --output comparison.json
```

Baseline comparison exit codes:

- `0` — no new or regressed finding and no active expired exception.
- `1` — new/regressed reliability debt or an expired exception that still targets a current known finding.
- `2` — invalid input, schema, or date.

The evaluation date is explicit. ERPChaos does not read the wall clock for exception decisions.

## Expiring exceptions

Exceptions are governance records, not technical baselines. Each exception must identify exactly one fingerprint and include an owner, reason, and expiry date:

```json
{
  "schema": "erpchaos.baseline-exceptions.v1",
  "exceptions": [
    {
      "fingerprint": "<exact-sha256-fingerprint>",
      "owner": "finance-platform-team",
      "reason": "legacy reliability debt scheduled for remediation",
      "expires_on": "2026-09-30"
    }
  ]
}
```

An exception can accept only an exact `KNOWN` finding. It cannot suppress a `NEW` or `REGRESSED` finding. If an exception expires while its known finding is still present, evaluation fails closed. An expired exception for a finding that has already become `RESOLVED` does not block the gate.

## Policy integration

The v0.16 policy behavior remains unchanged when no baseline is supplied.

With a baseline, only known findings covered by exact, non-expired exceptions are removed from policy enforcement. They remain in canonical findings and SARIF so the accepted debt is still observable.

```bash
erpchaos policy evaluate \
  CONTRACT.yaml \
  STATE.yaml \
  POLICY.yaml \
  --baseline baseline.json \
  --exceptions exceptions.json \
  --evaluation-date 2026-09-07 \
  --findings-output findings.json \
  --sarif-output results.sarif \
  --baseline-report-output baseline-report.json
```

`NEW` and `REGRESSED` findings remain visible to the normal severity policy. Expired exceptions force policy failure even if the normal severity threshold would otherwise pass.

## Determinism

Canonical baseline and comparison documents are JSON with sorted keys, compact separators, UTF-8 encoding, and a trailing newline. CI byte-compares outputs produced on Python 3.11 and 3.12.

ERPChaos does not use AI/LLMs, network calls, wildcard suppression, or system time in baseline classification and exception enforcement.
