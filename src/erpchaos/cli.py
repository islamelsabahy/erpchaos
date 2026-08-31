from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.engine import reliability_score, verify_contract
from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.models import BusinessReliabilityContract
from erpchaos.replay import replay

app = typer.Typer(help="Chaos engineering for ERP and business transactions.", no_args_is_help=True)
chaos_app = typer.Typer(
    help="Run deterministic business transaction chaos scenarios.",
    no_args_is_help=True,
)
app.add_typer(chaos_app, name="chaos")
console = Console()


@app.callback()
def main() -> None:
    """ERPChaos command-line interface."""


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Expected a YAML object in {path}")
    return data


@app.command()
def verify(contract: Path, state: Path) -> None:
    """Verify a transaction state against a Business Reliability Contract."""
    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
    except ValidationError as exc:
        console.print(f"[red]Invalid BRC:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    results = verify_contract(brc, _load_yaml(state))
    table = Table(title=f"ERPChaos — {brc.name}")
    table.add_column("Invariant")
    table.add_column("Result")
    table.add_column("Severity")
    table.add_column("Actual")
    table.add_column("Expected")

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        table.add_row(
            result.name,
            status,
            result.severity.upper(),
            repr(result.actual),
            repr(result.expected),
        )

    console.print(table)
    score = reliability_score(results)
    console.print(f"Business Reliability Score: [bold]{score}/100[/bold]")

    if any(not result.passed for result in results):
        raise typer.Exit(code=1)


@chaos_app.command("run")
def chaos_run(scenario: Path, stream: Path) -> None:
    """Apply a deterministic chaos scenario to an ordered business event stream."""
    try:
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
    except ValidationError as exc:
        console.print(f"[red]Invalid chaos input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    result = replay(event_stream, chaos_scenario)
    table = Table(title=f"ERPChaos Replay — {result.scenario}")
    table.add_column("#", justify="right")
    table.add_column("Event ID")
    table.add_column("Event Type")

    for index, event in enumerate(result.mutated_events, start=1):
        table.add_row(str(index), event.event_id, event.event_type)

    console.print(table)
    console.print(f"Transaction: [bold]{result.transaction_id}[/bold]")
    console.print(
        f"Events: {len(result.original_events)} → {len(result.mutated_events)} | "
        f"Changed: {'yes' if result.changed else 'no'}"
    )


if __name__ == "__main__":
    app()
