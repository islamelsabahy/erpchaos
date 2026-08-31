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
- `dependency review`

Do not require a release job on normal pull requests; release is tag-triggered only.

## Workflow trust policy

- Repository workflows default to `contents: read`.
- Release-only permissions are scoped to the release job.
- External GitHub Actions are pinned to immutable commit SHAs.
- Dependabot may propose dependency/action updates, but CI must pass before merge.
- PR dependency review rejects newly introduced high/critical vulnerable dependencies.

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
3. requires byte-identical package artifacts;
4. validates metadata with Twine;
5. installs the wheel into a clean virtual environment;
6. generates a reproducible CycloneDX SBOM from that environment;
7. creates GitHub/Sigstore provenance and SBOM attestations;
8. records SHA-256 checksums;
9. creates the GitHub Release.

PyPI publishing is deliberately excluded until Trusted Publishing is configured separately. Do not add API tokens to the repository.

## Verification

For a downloaded GitHub release, verify checksums first:

```bash
sha256sum -c SHA256SUMS
```

GitHub artifact attestations can additionally be verified with the GitHub CLI against this repository.

## Connected-tool limitation

The connected GitHub integration used to maintain this repository can read branch protection and rulesets but does not expose a write operation for repository rules. The ruleset itself therefore has to be enabled once in GitHub repository settings; all workflow-side controls live in version control.
