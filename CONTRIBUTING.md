# Contributing to ERPChaos

ERPChaos is building an open-source discipline around business transaction chaos engineering.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
pytest
```

## Contribution principles

- Prefer deterministic tests over AI-generated pass/fail decisions.
- Treat business invariants as first-class testable contracts.
- Add tests for every new operator, fault type, adapter, or scoring rule.
- Keep vendor-specific integrations isolated under adapters.
- Never use real customer data in examples or fixtures.
- Preserve backward compatibility for published BRC schemas when possible.

## Commit style

Use Conventional Commits:

- `feat:` new behavior
- `fix:` bug fix
- `test:` test-only changes
- `docs:` documentation
- `refactor:` internal restructuring
- `ci:` CI/CD changes
- `chore:` maintenance

## Pull requests

A good pull request should explain:

1. The business reliability problem being solved.
2. The failure mode or invariant involved.
3. How the behavior is tested.
4. Any compatibility or security implications.
