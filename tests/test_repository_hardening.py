from __future__ import annotations

import re
import tomllib
from pathlib import Path

import erpchaos

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
IMMUTABLE_ACTION_REF = re.compile(r"^[0-9a-f]{40}$")


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert erpchaos.__version__ == project["project"]["version"]


def test_external_github_actions_are_pinned_to_full_commit_shas() -> None:
    files = [REPOSITORY_ROOT / "action.yml"]
    files.extend(sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")))
    files.extend(sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yaml")))

    mutable_references: list[str] = []
    for path in files:
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line.startswith("uses:") and " uses:" not in raw_line:
                continue
            reference = line.split("uses:", maxsplit=1)[1].strip().split()[0]
            if reference.startswith("./") or "@" not in reference:
                continue
            _, revision = reference.rsplit("@", maxsplit=1)
            if not IMMUTABLE_ACTION_REF.fullmatch(revision):
                relative = path.relative_to(REPOSITORY_ROOT)
                mutable_references.append(f"{relative}:{line_number}: {reference}")

    assert not mutable_references, "Mutable GitHub Action references:\n" + "\n".join(
        mutable_references
    )
