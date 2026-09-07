from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.adapters.opentelemetry import translate_otlp_json
from erpchaos.trace import (
    TraceProjectionError,
    TransactionTrace,
    diagnose_trace,
    diagnostics_json,
    project_trace,
)

trace_app = typer.Typer(
    help="Inspect, validate, adapt, and project sanitized business transaction traces.",
    no_args_is_help=True,
)
console = Console()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML object in {path}")
    return data


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return data


def _load_trace(path: Path) -> TransactionTrace:
    return TransactionTrace.model_validate(_load_yaml(path))


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _render_input_error(exc: Exception) -> None:
    console.print(f"[red]Invalid transaction trace:[/red] {exc}")


def _render_trace_issues(trace: TransactionTrace) -> bool:
    diagnostics = diagnose_trace(trace)
    for issue in diagnostics.issues:
        console.print(f"- {issue.code}: {issue.message} ({issue.issue_id})")
    return diagnostics.valid


@trace_app.command("inspect")
def inspect_command(
    document: Path,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic machine-readable JSON."),
    ] = False,
) -> None:
    """Inspect canonical trace identity and correlation metadata."""

    try:
        trace = _load_trace(document)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_input_error(exc)
        raise typer.Exit(code=2) from exc

    source_systems = sorted({event.source_system for event in trace.events})
    payload: dict[str, object] = {
        "event_count": len(trace.events),
        "schema": trace.schema_version,
        "source_systems": source_systems,
        "trace_id": trace.trace_id,
        "transaction_id": trace.transaction_id,
    }
    if json_output:
        typer.echo(_canonical_json(payload), nl=False)
        return

    table = Table(title="ERPChaos Transaction Trace")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Schema", trace.schema_version)
    table.add_row("Trace", trace.trace_id)
    table.add_row("Transaction", trace.transaction_id)
    table.add_row("Events", str(len(trace.events)))
    table.add_row("Source systems", ", ".join(source_systems))
    console.print(table)


@trace_app.command("validate")
def validate_command(
    document: Path,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic trace diagnostics JSON."),
    ] = False,
) -> None:
    """Validate identities and causal links without inferring missing relationships."""

    try:
        trace = _load_trace(document)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_input_error(exc)
        raise typer.Exit(code=2) from exc

    diagnostics = diagnose_trace(trace)
    if json_output:
        typer.echo(diagnostics_json(diagnostics), nl=False)
    else:
        status = "PASS" if diagnostics.valid else "FAIL"
        console.print(f"Trace validation: [bold]{status}[/bold]")
        console.print(f"Trace: [bold]{diagnostics.trace_id}[/bold]")
        console.print(f"Transaction: [bold]{diagnostics.transaction_id}[/bold]")
        if diagnostics.ordered_event_ids:
            console.print("Ordered path: " + " -> ".join(diagnostics.ordered_event_ids))
        for issue in diagnostics.issues:
            console.print(f"- {issue.code}: {issue.message} ({issue.issue_id})")

    if not diagnostics.valid:
        raise typer.Exit(code=1)


@trace_app.command("from-otel")
def from_otel_command(
    document: Path,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write canonical transaction-trace YAML to this path."),
    ] = None,
    diagnostics_output: Annotated[
        Path | None,
        typer.Option("--diagnostics", help="Optionally write deterministic diagnostics JSON."),
    ] = None,
) -> None:
    """Translate one sanitized offline OTLP JSON export without any network access."""

    try:
        trace = translate_otlp_json(_load_json(document))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        _render_input_error(exc)
        raise typer.Exit(code=2) from exc

    diagnostics = diagnose_trace(trace)
    if diagnostics_output is not None:
        diagnostics_output.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_output.write_text(diagnostics_json(diagnostics), encoding="utf-8")
    if not diagnostics.valid:
        console.print("[red]OTLP translation refused:[/red] invalid or ambiguous correlation")
        _render_trace_issues(trace)
        raise typer.Exit(code=1)

    text = yaml.safe_dump(
        trace.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
    )
    if output is None:
        typer.echo(text, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    console.print(f"Canonical transaction trace: [bold]{output}[/bold]")


@trace_app.command("project")
def project_command(
    document: Path,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write the projected EventStream YAML to this path."),
    ] = None,
    diagnostics_output: Annotated[
        Path | None,
        typer.Option("--diagnostics", help="Optionally write deterministic diagnostics JSON."),
    ] = None,
) -> None:
    """Project a valid trace into the vendor-neutral ERPChaos EventStream model."""

    try:
        trace = _load_trace(document)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_input_error(exc)
        raise typer.Exit(code=2) from exc

    diagnostics = diagnose_trace(trace)
    if diagnostics_output is not None:
        diagnostics_output.parent.mkdir(parents=True, exist_ok=True)
        diagnostics_output.write_text(diagnostics_json(diagnostics), encoding="utf-8")

    try:
        stream = project_trace(trace)
    except TraceProjectionError as exc:
        console.print("[red]Trace projection refused:[/red] invalid or ambiguous correlation")
        for issue in exc.diagnostics.issues:
            console.print(f"- {issue.code}: {issue.message} ({issue.issue_id})")
        raise typer.Exit(code=1) from exc

    text = yaml.safe_dump(stream.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    if output is None:
        typer.echo(text, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    console.print(f"Projected EventStream: [bold]{output}[/bold]")
