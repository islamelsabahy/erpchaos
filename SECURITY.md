# Security Policy

ERPChaos intentionally interacts with business workflows and will eventually support fault injection and transaction replay. Treat those capabilities as potentially disruptive.

## Supported versions

ERPChaos is currently pre-1.0. Security fixes are applied to the latest development version.

## Reporting a vulnerability

Please do not publish exploitable security issues, credentials, production data, or sensitive ERP configuration in a public issue.

Until a dedicated private reporting channel is configured, open a minimal public issue stating that a security concern exists without including exploit details or sensitive data.

## Safety principles

- Do not target production systems by default.
- Do not commit production credentials or customer data.
- Replay datasets must be anonymized before use.
- Fault injection adapters must require explicit target configuration.
- Destructive operations should require explicit opt-in and clearly identify the target environment.
- Reliability checks must remain deterministic and auditable.
