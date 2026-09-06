from __future__ import annotations

from erpchaos.cli import app
from erpchaos.evidence_cli import evidence_app
from erpchaos.spec_cli import spec_app

app.add_typer(evidence_app, name="evidence")
app.add_typer(spec_app, name="spec")
