from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.adapters.odoo import (
    OdooExportAdapter,
    OdooExportFixture,
    export_event_stream_document,
)
from erpchaos.concurrency import ConcurrencyScenario, run_concurrency
from erpchaos.engine import InvariantResult, reliability_score, verify_contract
from erpchaos.events import EventStream
from erpchaos.experiment import run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.incidents import (
    IncidentSanitizationPolicy,
    sanitize_event_stream,
    validate_sanitized_event_stream,
)
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import (
    RecoveryContract,
    RecoveryScenario,
    run_recovery_experiment,
)
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
recovery_app = typer.Typer(
    help="Run deterministic business recovery experiments after chaos-induced failures.",
    no_args_is_help=True,
)
adapter_app = typer.Typer(
    help="Translate ERP-specific activity into vendor-neutral ERPChaos fixtures.",
    no_args_is_help=True,
)
odoo_app = typer.Typer(
    help="Translate safe read-only Odoo exports.",
    no_args_is_help=True,
)
incident_app = typer.Typer(
    help="Sanitize production-derived incidents into safe deterministic replay fixtures.",
    no_args_is_help=True,
)
adapter_app.add_typer(odoo_app, name="odoo")
app.add_typer(chaos_app, name="chaos")
app.add_typer(experiment_app, name="experiment")
app.add_typer(concurrency_app, name="concurrency")
app.add_typer(recovery_app, name="recovery")
app.add_typer(adapter_app, name="adapter")
app.add_typer(incident_app, name="incident")
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


@recovery_app.command("run")
def recovery_run(
    contract: Path,
    scenario: Path,
    stream: Path,
    recovery_contract: Path,
    recovery_scenario: Path,
) -> None:
    """Run chaos, apply compensating events, and score business recovery deterministically."""
    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        recovery_brc = RecoveryContract.model_validate(_load_yaml(recovery_contract))
        recovery = RecoveryScenario.model_validate(_load_yaml(recovery_scenario))
        result = run_recovery_experiment(
            brc,
            chaos_scenario,
            event_stream,
            recovery_brc,
            recovery,
        )
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid recovery input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title=f"ERPChaos Recovery — {result.recovery_scenario}")
    table.add_column("Step", justify="right")
    table.add_column("Event ID")
    table.add_column("Event Type")
    table.add_column("RRS", justify="right")
    table.add_column("Consistent")
    for checkpoint in result.checkpoints:
        table.add_row(
            str(checkpoint.step),
            checkpoint.event_id,
            checkpoint.event_type,
            str(checkpoint.score),
            "YES" if checkpoint.passed else "NO",
        )
    console.print(table)
    _render_invariants(f"Recovery Contract — {recovery_brc.name}", result.invariant_results)
    ttbc = "not reached" if result.ttbc_steps is None else str(result.ttbc_steps)
    console.print(f"Recovery Status: [bold]{result.status.value}[/bold]")
    console.print(f"Recovery Reliability Score: [bold]{result.score}/100[/bold]")
    console.print(f"Time to Business Consistency: [bold]{ttbc} event step(s)[/bold]")
    console.print(
        "Regressed after recovery: "
        f"[bold]{'YES' if result.regressed_after_recovery else 'NO'}[/bold]"
    )

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


@incident_app.command("sanitize")
def incident_sanitize(
    stream: Path,
    policy: Path,
    output: Path | None = None,
) -> None:
    """Create a replay-safe incident fixture using a runtime pseudonymization key."""
    if output is None:
        console.print("[red]Invalid incident input:[/red] --output is required")
        raise typer.Exit(code=2)

    pseudonym_key = os.environ.get("ERPCHAOS_PSEUDONYM_KEY", "")
    if not pseudonym_key:
        console.print(
            "[red]Invalid incident input:[/red] ERPCHAOS_PSEUDONYM_KEY is required at runtime"
        )
        raise typer.Exit(code=2)

    try:
        event_stream = EventStream.model_validate(_load_yaml(stream))
        sanitization_policy = IncidentSanitizationPolicy.model_validate(_load_yaml(policy))
        result = sanitize_event_stream(event_stream, sanitization_policy, pseudonym_key)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid incident input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(result.stream.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    console.print("Incident sanitization: [bold]PASS[/bold]")
    console.print(f"Policy: [bold]{sanitization_policy.name}[/bold]")
    console.print(f"Events preserved: [bold]{len(result.stream.events)}[/bold]")
    console.print(f"Transformed fields: [bold]{result.transformed_fields}[/bold]")
    console.print(f"Dropped fields: [bold]{result.dropped_fields}[/bold]")
    console.print(f"Safe replay fixture: [bold]{output}[/bold]")


@incident_app.command("validate")
def incident_validate(fixture: Path) -> None:
    """Validate that an incident fixture contains only replay-safe pseudonymized data."""
    try:
        event_stream = EventStream.model_validate(_load_yaml(fixture))
        validate_sanitized_event_stream(event_stream)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Unsafe incident fixture:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print("Incident fixture validation: [bold]PASS[/bold]")
    console.print(f"Events: [bold]{len(event_stream.events)}[/bold]")


@odoo_app.command("translate")
def odoo_translate(fixture: Path, output: Path | None = None) -> None:
    """Translate a sanitized read-only Odoo export into ERPChaos event streams."""
    try:
        odoo_fixture = OdooExportFixture.model_validate(_load_yaml(fixture))
        streams = OdooExportAdapter(odoo_fixture).translate()
        document = export_event_stream_document(streams)
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid Odoo adapter input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title="ERPChaos Odoo Read Adapter")
    table.add_column("Transaction")
    table.add_column("Events", justify="right")

    for stream in streams:
        table.add_row(stream.transaction_id, str(len(stream.events)))

    console.print(table)
    console.print(
        f"Environment: [bold]{odoo_fixture.config.environment.value}[/bold] | "
        "Mode: [bold]READ ONLY[/bold]"
    )
    console.print(f"Translated streams: [bold]{len(streams)}[/bold]")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            yaml.safe_dump(document, sort_keys=False),
            encoding="utf-8",
        )
        console.print(f"Sanitized export: [bold]{output}[/bold]")


if __name__ == "__main__":
    app()
