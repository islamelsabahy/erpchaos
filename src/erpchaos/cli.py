from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.concurrency import ConcurrencyScenario, run_concurrency
from erpchaos.engine import InvariantResult, reliability_score, verify_contract
from erpchaos.events import EventStream
from erpchaos.experiment import run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.models import BusinessReliabilityContract
from erpchaos.replay import replay

app = typer.Typer(
    help="Chaos engineering for ERP and business transactions.",
    no_args_is_help=True,
)
chaos_app = typer.Typer(
    help="Run deterministic business transaction chaos scenarios.",
    no_args_is_help=True,
)
experiment_app = typer.Typer(
    help="Run chaos experiments and evaluate Business Reliability Contracts.",
    no_args_is_help=True,
)
concurrency_app = typer.Typer(
    help="Run deterministic competing-transaction experiments.",
    no_args_is_help=True,
)
app.add_typer(chaos_app, name="chaos")
app.add_typer(experiment_app, name="experiment")
app.add_typer(concurrency_app, name="concurrency")
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


def _render_invariants(title: str, results: list[InvariantResult]) -> int:
    table = Table(title=title)
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
    return score


@app.command()
def verify(contract: Path, state: Path) -> None:
    """Verify a transaction state against a Business Reliability Contract."""
    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
    except ValidationError as exc:
        console.print(f"[red]Invalid BRC:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    results = verify_contract(brc, _load_yaml(state))
    _render_invariants(f"ERPChaos — {brc.name}", results)

    if any(not result.passed for result in results):
        raise typer.Exit(code=1)


@chaos_app.command("run")
def chaos_run(scenario: Path, stream: Path) -> None:
    """Apply a deterministic chaos scenario to an ordered business event stream."""
    try:
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        result = replay(event_stream, chaos_scenario)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid chaos input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

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


@experiment_app.command("run")
def experiment_run(contract: Path, scenario: Path, stream: Path) -> None:
    """Run chaos against an event stream and evaluate the resulting business state."""
    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        result = run_experiment(brc, chaos_scenario, event_stream)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid experiment input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(
        f"Experiment: [bold]{chaos_scenario.name}[/bold] | "
        f"Transaction: [bold]{event_stream.transaction_id}[/bold]"
    )
    console.print(
        f"Events: {len(result.replay.original_events)} → "
        f"{len(result.replay.mutated_events)}"
    )
    _render_invariants(f"Post-chaos BRC — {brc.name}", result.invariant_results)

    if not result.passed:
        raise typer.Exit(code=1)


@concurrency_app.command("run")
def concurrency_run(scenario: Path) -> None:
    """Run a deterministic race between transactions sharing one resource."""
    try:
        concurrency_scenario = ConcurrencyScenario.model_validate(_load_yaml(scenario))
        result = run_concurrency(concurrency_scenario)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid concurrency input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title=f"ERPChaos Concurrency — {result.scenario}")
    table.add_column("#", justify="right")
    table.add_column("Transaction")
    table.add_column("Event ID")
    table.add_column("Event Type")

    for item in result.timeline:
        table.add_row(
            str(item.position),
            item.transaction_id,
            item.event.event_id,
            item.event.event_type,
        )

    console.print(table)
    winners = ", ".join(result.successful_transactions) or "none"
    race_status = "CLEAR" if result.passed else "DETECTED"
    console.print(f"Resource: [bold]{result.resource_key}[/bold]")
    console.print(
        f"Successful transactions: {len(result.successful_transactions)} "
        f"(allowed: {result.max_successes}) | {winners}"
    )
    console.print(f"Business Race Condition: [bold]{race_status}[/bold]")
    console.print(f"Business Reliability Score: [bold]{result.score}/100[/bold]")

    if not result.passed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
