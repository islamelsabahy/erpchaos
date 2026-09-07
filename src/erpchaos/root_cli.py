from __future__ import annotations

from erpchaos.baseline_cli import baseline_app
from erpchaos.cli import app
from erpchaos.evidence_cli import evidence_app
from erpchaos.policy_cli import policy_app
from erpchaos.spec_cli import spec_app
from erpchaos.trace_cli import trace_app

app.add_typer(baseline_app, name="baseline")
app.add_typer(evidence_app, name="evidence")
app.add_typer(policy_app, name="policy")
app.add_typer(spec_app, name="spec")
app.add_typer(trace_app, name="trace")

if __name__ == "__main__":
    app()
