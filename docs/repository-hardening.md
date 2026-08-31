# ERPChaos Repository Hardening

ERPChaos keeps business-reliability decisions deterministic and keeps repository/release controls outside the decision engine.

## Main-branch ruleset target

Create a branch ruleset targeting the default branch (`main`) with these settings:

- Require a pull request before merging.
- Required approvals: `0` while the repository has a single maintainer. Raise this when independent reviewers are available.
- Require conversation resolution before merging.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.
- Block force pushes.
- Block branch deletion.
- Require linear history.
- Require signed commits on `main`.
- Allow repository-administrator bypass only for emergency recovery.

### Required status checks

After the workflows have run at least once, require these checks:

- `test (3.11)`
- `test (3.12)`
- `evidence byte consistency`
- `composite action contract`
- `reproducible package build`
- `dependency audit`

Do not require a release job on normal pull requests; release is tag-triggered only.

## Workflow trust policy

- Repository workflows default to `contents: read`.
- Release-only permissions are scoped to the release job.
- External GitHub Actions are pinned to immutable commit SHAs.
- The Python build backend is pinned for packaging reproducibility.
- Dependabot may propose dependency/action updates, but CI must pass before merge.
- `pip-audit --strict .` audits resolved project dependencies on pull requests and pushes to `main`.

### GitHub Dependency Review

GitHub's native Dependency Review action requires the repository **Dependency graph** setting. If Dependency graph is enabled later under repository security settings, native Dependency Review can be added as an additional PR gate. The executable `dependency audit` gate does not depend on that repository setting and remains mandatory.

## Release policy

Release tags must exactly match the PEP 440 package version prefixed with `v`.

Example:

```text
package version: 0.14.0a0
tag:             v0.14.0a0
```

The release workflow:

1. verifies tag/version equality;
2. builds wheel and sdist twice using the same `SOURCE_DATE_EPOCH`;
3. requires byte-identical wheel artifacts;
4. requires extracted sdist contents to be identical, avoiding false failures from gzip envelope metadata;
5. validates metadata with Twine;
6. installs the wheel into a clean virtual environment;
7. generates a reproducible CycloneDX SBOM from that environment;
8. creates GitHub/Sigstore provenance and SBOM attestations;
9. records SHA-256 checksums;
10. creates the GitHub Release.

PyPI publishing is deliberately excluded until Trusted Publishing is configured separately. Do not add API tokens to the repository.

## Verification

For a downloaded GitHub release, verify checksums first:

```bash
sha256sum -c SHA256SUMS
```

GitHub artifact attestations can additionally be verified with the GitHub CLI against this repository.

## Connected-tool limitations

The connected GitHub integration used to maintain this repository can read branch protection, rulesets, and security state, but does not expose write operations for the repository rules or Dependency graph setting. Those repository-level controls therefore require a one-time GitHub Settings change; workflow-side controls remain versioned in the repository.
