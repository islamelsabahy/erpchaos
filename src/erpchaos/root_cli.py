from __future__ import annotations

from erpchaos.cli import app
from erpchaos.evidence_cli import evidence_app

app.add_typer(evidence_app, name="evidence")
