# Policy Gates and SARIF

ERPChaos v0.16 adds a deterministic policy layer between business-reliability evaluation and external CI/reporting systems.

The design intentionally separates three concerns:

```text
BRC + Transaction State
        |
        v
Invariant Evaluation
        |
        v
Vendor-neutral Findings
        |
        +--> Policy Gate --> PASS / FAIL
        |
        +--> Canonical JSON
        |
        +--> SARIF 2.1.0 Renderer --> Code Scanning / other SARIF consumers
```

SARIF is an output adapter. GitHub, Code Scanning, and other SARIF consumers do **not** decide whether an ERPChaos business policy passes. The deterministic ERPChaos policy engine does.

## Policy Gate

A policy controls the minimum severity that fails CI:

```yaml
schema: erpchaos.policy-gate.v1
name: Strict Business Reliability Gate
fail_on_or_above: high
ignored_rule_ids: []
```

Severity order is:

```text
low < medium < high < critical
```

For `fail_on_or_above: high`, low and medium findings are reported but do not fail the policy. High and critical findings fail it unless their stable rule IDs are explicitly ignored.

`ignored_rule_ids` is deliberately explicit. ERPChaos does not silently suppress findings based on names, text matching, or AI judgment.

## Stable findings

Each failed BRC invariant becomes one vendor-neutral finding with:

- stable `rule_id`
- source kind
- contract and transaction identity
- invariant name and path
- severity
- deterministic message
- actual and expected values
- optional source URI

BRC rule IDs use the prefix `ERPCHAOS-BRC-` plus a truncated SHA-256 digest of:

```text
transaction
invariant_name
invariant_path
```

This avoids order-dependent numeric IDs while keeping the ID stable when unrelated invariants are added or reordered.

Canonical findings documents use:

```text
erpchaos.findings.v1
```

Policy evaluations use:

```text
erpchaos.policy-evaluation.v1
```

## CLI

Evaluate a static transaction state against a BRC and policy:

```bash
set +e
erpchaos policy evaluate \
  examples/real-estate/property-sale.brc.yaml \
  examples/real-estate/policy-failing-state.synthetic.yaml \
  examples/policy/strict-business-gate.yaml \
  --findings-output /tmp/erpchaos-findings.json \
  --sarif-output /tmp/erpchaos-results.sarif
status=$?
set -e
```

Exit codes:

- `0` — policy passed
- `1` — policy violation
- `2` — invalid input/configuration

Artifacts are written before exit `1`, so CI can upload or archive findings even when enforcement fails.

Render an existing canonical findings document to SARIF:

```bash
erpchaos policy sarif \
  /tmp/erpchaos-findings.json \
  --output /tmp/erpchaos-results.sarif
```

The renderer is deterministic. Re-rendering the same canonical findings produces byte-identical SARIF.

## SARIF mapping

ERPChaos renders SARIF 2.1.0.

Severity mapping:

| ERPChaos | SARIF level |
| --- | --- |
| `low` | `note` |
| `medium` | `warning` |
| `high` | `error` |
| `critical` | `error` |

The original ERPChaos severity is also retained in SARIF result properties, so `high` and `critical` remain distinguishable even though both use the SARIF `error` level.

Rules and results are sorted deterministically by stable rule identity.

## GitHub Action

The composite Action supports `mode: policy`:

```yaml
- name: Run ERPChaos policy
  id: erpchaos
  continue-on-error: true
  uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: policy
    contract: reliability/property-sale.brc.yaml
    state: reliability/transaction-state.yaml
    policy: reliability/policy-gate.yaml
    findings-output: .erpchaos/findings.json
    sarif-output: .erpchaos/results.sarif
```

Policy failure publishes:

```text
status=POLICY_FAILURE
exit-code=1
```

Use `continue-on-error: true` when SARIF must still be uploaded after a failed gate, then enforce the output in a later step.

## GitHub Code Scanning

A complete consumer workflow is available at:

```text
examples/github-actions/policy-sarif-code-scanning.yml
```

The example uses the official `github/codeql-action/upload-sarif` action pinned to an immutable commit SHA. It grants only:

```yaml
permissions:
  contents: read
  security-events: write
```

The workflow pattern is:

1. run ERPChaos policy with `continue-on-error: true`;
2. generate canonical JSON and SARIF;
3. upload SARIF to Code Scanning with `if: always()`;
4. enforce ERPChaos `exit-code` in a final step.

That separation preserves both reporting and enforcement.

## Determinism gates

Repository CI runs policy output generation on Python 3.11 and Python 3.12, then proves byte equality for:

- canonical findings JSON
- SARIF JSON

The workflow also round-trips findings through `erpchaos policy sarif` and compares the bytes with the SARIF emitted directly by `policy evaluate`.

## Safety and trust boundaries

Policy evaluation and SARIF rendering:

- do not require network access;
- do not mutate an ERP;
- do not use LLMs or probabilistic scoring;
- do not send transaction data to GitHub unless the caller explicitly uploads the generated SARIF;
- retain ERPChaos as the source of pass/fail truth.

Only synthetic examples belong in the public repository. Production-derived incident data must continue through the incident sanitization workflow before becoming replay or policy-test fixtures.
