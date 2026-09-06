from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.spec import (
    CompatibilityStatus,
    compare_specs,
    compatibility_json,
    inspect_spec,
    normalize_spec,
    registered_schemas,
)

spec_app = typer.Typer(
    help="Inspect, validate, normalize, and compare ERPChaos specification documents.",
    no_args_is_help=True,
)
console = Console()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML object in {path}")
    return data


def _inspection_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _render_error(prefix: str, exc: Exception) -> None:
    console.print(f"[red]{prefix}:[/red] {exc}")


@spec_app.command("registry")
def registry() -> None:
    """List the canonical specification schema IDs supported by this ERPChaos build."""

    table = Table(title="ERPChaos Specification Registry")
    table.add_column("Schema")
    for schema in registered_schemas():
        table.add_row(schema)
    console.print(table)


@spec_app.command("inspect")
def inspect_command(
    document: Path,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic machine-readable JSON."),
    ] = False,
) -> None:
    """Identify and validate one ERPChaos specification document."""

    try:
        inspection = inspect_spec(_load_yaml(document))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_error("Invalid specification", exc)
        raise typer.Exit(code=2) from exc

    if json_output:
        typer.echo(
            _inspection_json(
                inspection.model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
            nl=False,
        )
        return

    table = Table(title="ERPChaos Specification")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Kind", inspection.kind.value)
    table.add_row("Schema", inspection.schema_version)
    table.add_row("Legacy implicit schema", "YES" if inspection.legacy_implicit_schema else "NO")
    table.add_row("Name", inspection.name or "-")
    console.print(table)


@spec_app.command("validate")
def validate_command(
    document: Path,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic machine-readable JSON."),
    ] = False,
) -> None:
    """Validate one document against the authoritative registered schema model."""

    try:
        inspection = inspect_spec(_load_yaml(document))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_error("Invalid specification", exc)
        raise typer.Exit(code=2) from exc

    payload = {
        "kind": inspection.kind.value,
        "legacy_implicit_schema": inspection.legacy_implicit_schema,
        "name": inspection.name,
        "schema": inspection.schema_version,
        "valid": True,
    }
    if json_output:
        typer.echo(_inspection_json(payload), nl=False)
        return

    console.print("Specification validation: [bold]PASS[/bold]")
    console.print(f"Kind: [bold]{inspection.kind.value}[/bold]")
    console.print(f"Schema: [bold]{inspection.schema_version}[/bold]")


@spec_app.command("normalize")
def normalize_command(
    document: Path,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write canonical YAML to this path."),
    ] = None,
) -> None:
    """Normalize a valid document to canonical YAML with an explicit schema identity."""

    try:
        canonical = normalize_spec(_load_yaml(document))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_error("Invalid specification", exc)
        raise typer.Exit(code=2) from exc

    text = yaml.safe_dump(canonical, sort_keys=False, allow_unicode=True)
    if output is None:
        typer.echo(text, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    console.print(f"Canonical specification: [bold]{output}[/bold]")


@spec_app.command("compare")
def compare_command(
    old: Path,
    new: Path,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic machine-readable JSON."),
    ] = False,
) -> None:
    """Compare old -> new specification semantics and classify compatibility."""

    try:
        report = compare_specs(_load_yaml(old), _load_yaml(new))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        _render_error("Invalid specification comparison", exc)
        raise typer.Exit(code=2) from exc

    if json_output:
        typer.echo(compatibility_json(report), nl=False)
    else:
        table = Table(title="ERPChaos Specification Compatibility")
        table.add_column("Field")
        table.add_column("Old")
        table.add_column("New")
        table.add_row("Kind", report.old.kind.value, report.new.kind.value)
        table.add_row("Schema", report.old.schema_version, report.new.schema_version)
        table.add_row("Name", report.old.name or "-", report.new.name or "-")
        console.print(table)
        console.print(f"Compatibility: [bold]{report.status.value}[/bold]")
        if report.reasons:
            for reason in report.reasons:
                console.print(f"- {reason}")

    if report.status in {
        CompatibilityStatus.behavioral_change,
        CompatibilityStatus.incompatible,
    }:
        raise typer.Exit(code=1)
