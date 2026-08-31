# ERPChaos GitHub Action

ERPChaos can run as a deterministic CI/CD business-reliability gate without requiring a consumer repository to install the Python package manually.

## Version-pinned usage

Pin the action to an explicit release tag:

```yaml
- name: Verify business reliability
  uses: islamelsabahy/erpchaos@v0.7.0-alpha
  with:
    mode: verify
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml
```

For maximum supply-chain immutability, consumers may replace the tag with the exact commit SHA resolved for that release.

## Modes

### `verify`

Required inputs: `contract`, `state`.

```yaml
- uses: islamelsabahy/erpchaos@v0.7.0-alpha
  with:
    mode: verify
    contract: reliability/property-sale.brc.yaml
    state: reliability/property-sale-state.yaml
```

### `chaos`

Required inputs: `scenario`, `stream`.

```yaml
- uses: islamelsabahy/erpchaos@v0.7.0-alpha
  with:
    mode: chaos
    scenario: reliability/duplicate-payment.scenario.yaml
    stream: reliability/property-sale.events.yaml
```

### `experiment`

Required inputs: `contract`, `scenario`, `stream`.

```yaml
- uses: islamelsabahy/erpchaos@v0.7.0-alpha
  with:
    mode: experiment
    contract: reliability/property-sale.events.brc.yaml
    scenario: reliability/duplicate-payment.scenario.yaml
    stream: reliability/property-sale.events.yaml
```

## Inputs

| Input | Required | Purpose |
| --- | --- | --- |
| `mode` | Yes | `verify`, `chaos`, or `experiment` |
| `contract` | By mode | Business Reliability Contract YAML |
| `state` | `verify` | Transaction-state YAML |
| `scenario` | `chaos`, `experiment` | Deterministic chaos scenario YAML |
| `stream` | `chaos`, `experiment` | Business event-stream YAML |
| `python-version` | No | Python runtime, default `3.12` |

All file paths are resolved from the consumer repository workspace after checkout.

## Outputs and exit-code contract

The Action exposes `status` and `exit-code`.

| Exit code | Status | Meaning |
| ---: | --- | --- |
| `0` | `PASS` | The requested reliability gate passed |
| `1` | `BUSINESS_FAILURE` | ERPChaos ran correctly and detected a failed business invariant |
| `2` | `INVALID_INPUT` | Required input, file, BRC, scenario, stream, or configuration is invalid |
| other | `EXECUTION_ERROR` | Unexpected execution/runtime error |

A business failure intentionally fails the GitHub Actions step. This makes ERPChaos usable as a deployment or pull-request gate while keeping business failures distinguishable from configuration errors.

## Job Summary

Every invocation appends an **ERPChaos Business Reliability Gate** section to the GitHub Actions Job Summary containing the mode, classified status, exit code, and captured ERPChaos CLI output. The summary is written before the Action returns the original ERPChaos exit code, so diagnostic information remains available when the gate fails.

## Outputs example

```yaml
- name: ERPChaos
  id: erpchaos
  uses: islamelsabahy/erpchaos@v0.7.0-alpha
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

The Action checks out no external ERP credentials, calls no AI service, uses the same deterministic ERPChaos engine as the CLI, installs ERPChaos from the pinned Action source itself, and preserves ERPChaos exit semantics.

See `examples/github-actions/erpchaos.yml` for a complete consumer workflow.
