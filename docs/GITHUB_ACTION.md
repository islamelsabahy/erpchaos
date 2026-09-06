# ERPChaos GitHub Action

ERPChaos can run as a deterministic CI/CD business-reliability gate without requiring a consumer repository to install the Python package manually.

## Immutable usage

Pin ERPChaos to an exact reviewed commit SHA:

```yaml
- name: Verify business reliability
  uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: verify
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml
```

Using the full commit SHA avoids depending on a mutable branch or tag and provides the strongest supply-chain immutability.

## Modes

### `verify`

Required inputs: `contract`, `state`.

```yaml
- uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: verify
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml
```

### `chaos`

Required inputs: `scenario`, `stream`.

```yaml
- uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: chaos
    scenario: reliability/duplicate-payment.scenario.yaml
    stream: reliability/property-sale.events.yaml
```

### `experiment`

Required inputs: `contract`, `scenario`, `stream`.

```yaml
- uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: experiment
    contract: reliability/property-sale.events.brc.yaml
    scenario: reliability/duplicate-payment.scenario.yaml
    stream: reliability/property-sale.events.yaml
```

### `policy`

Required inputs: `contract`, `state`, `policy`.

Optional outputs can be written to `findings-output` and `sarif-output` before the Action returns its policy exit code.

```yaml
- name: ERPChaos policy gate
  id: erpchaos
  continue-on-error: true
  uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: policy
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml
    policy: reliability/policy-gate.yaml
    findings-output: .erpchaos/findings.json
    sarif-output: .erpchaos/results.sarif
```

Use `continue-on-error: true` when a failed policy must still produce SARIF for a later upload step. Enforce `steps.erpchaos.outputs.exit-code` after the upload.

## Inputs

| Input | Required | Purpose |
| --- | --- | --- |
| `mode` | Yes | `verify`, `chaos`, `experiment`, or `policy` |
| `contract` | `verify`, `experiment`, `policy` | Business Reliability Contract YAML |
| `state` | `verify`, `policy` | Transaction-state YAML |
| `scenario` | `chaos`, `experiment` | Deterministic chaos scenario YAML |
| `stream` | `chaos`, `experiment` | Business event-stream YAML |
| `policy` | `policy` | Policy Gate YAML |
| `findings-output` | No | Canonical ERPChaos findings JSON path for policy mode |
| `sarif-output` | No | SARIF 2.1.0 output path for policy mode |
| `python-version` | No | Python runtime, default `3.12` |

All input file paths are resolved from the consumer repository workspace after checkout.

## Outputs and exit-code contract

The Action exposes `status` and `exit-code`.

| Exit code | Status | Meaning |
| ---: | --- | --- |
| `0` | `PASS` | The requested gate passed |
| `1` | `BUSINESS_FAILURE` | A verify/experiment business invariant failed |
| `1` | `POLICY_FAILURE` | Policy mode found one or more findings at or above its enforced threshold |
| `2` | `INVALID_INPUT` | Required input, file, contract, scenario, stream, policy, or configuration is invalid |
| other | `EXECUTION_ERROR` | Unexpected execution/runtime error |

Business and policy failures intentionally fail the Action step. This makes ERPChaos usable as a deployment or pull-request gate while keeping domain failures distinguishable from configuration/runtime errors.

## Job Summary

Every invocation appends an **ERPChaos Business Reliability Gate** section to the GitHub Actions Job Summary containing the mode, classified status, exit code, and captured ERPChaos CLI output. The summary is written before the Action returns the original ERPChaos exit code, so diagnostic information remains available when the gate fails.

## Policy findings and SARIF

Policy mode can write two deterministic machine-readable artifacts:

- `erpchaos.findings.v1` canonical JSON
- SARIF 2.1.0

ERPChaos remains the source of pass/fail truth. SARIF is a reporting adapter for external consumers such as GitHub Code Scanning.

See [`POLICY_SARIF.md`](POLICY_SARIF.md) and `examples/github-actions/policy-sarif-code-scanning.yml` for the full upload-and-enforce pattern.

## Outputs example

```yaml
- name: ERPChaos
  id: erpchaos
  uses: islamelsabahy/erpchaos@<PINNED_ERPCHAOS_COMMIT_SHA>
  with:
    mode: verify
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml

- name: Inspect ERPChaos result
  if: always()
  run: |
    echo "Status: ${{ steps.erpchaos.outputs.status }}"
    echo "Exit code: ${{ steps.erpchaos.outputs.exit-code }}"
```

## Deterministic and self-contained

The Action calls no AI service, requires no ERP credentials for these fixture-based modes, uses the same deterministic ERPChaos engine as the CLI, installs ERPChaos from the pinned Action source itself, and preserves ERPChaos exit semantics.

See `examples/github-actions/erpchaos.yml` for baseline consumer workflows.
