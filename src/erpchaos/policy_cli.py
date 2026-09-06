from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.engine import verify_contract
from erpchaos.models import BusinessReliabilityContract
from erpchaos.policy import (
    FindingDocument,
    PolicyGate,
    PolicyStatus,
    canonical_json,
    evaluate_policy,
    findings_from_invariants,
)
from erpchaos.sarif import canonical_sarif_json

policy_app = typer.Typer(
    help="Evaluate deterministic business reliability policy gates and render findings.",
    no_args_is_help=True,
)
console = Console()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected a YAML object in {path}")
    return data


@policy_app.command("evaluate")
def evaluate_command(
    contract: Path,
    state: Path,
    policy: Path,
    findings_output: Annotated[
        Path | None,
        typer.Option("--findings-output", help="Write canonical findings JSON."),
    ] = None,
    sarif_output: Annotated[
        Path | None,
        typer.Option("--sarif-output", help="Write deterministic SARIF 2.1.0 JSON."),
    ] = None,
) -> None:
    """Evaluate a transaction state, emit findings, and apply a policy threshold."""

    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        gate = PolicyGate.model_validate(_load_yaml(policy))
        results = verify_contract(brc, _load_yaml(state))
        findings = findings_from_invariants(brc, results, source_uri=contract.as_posix())
        evaluation = evaluate_policy(gate, findings)
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid policy input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if findings_output is not None:
        findings_output.parent.mkdir(parents=True, exist_ok=True)
        findings_output.write_text(
            canonical_json(FindingDocument(findings=findings)),
            encoding="utf-8",
        )
    if sarif_output is not None:
        sarif_output.parent.mkdir(parents=True, exist_ok=True)
        sarif_output.write_text(canonical_sarif_json(findings), encoding="utf-8")

    table = Table(title=f"ERPChaos Policy Gate — {gate.name}")
    table.add_column("Rule")
    table.add_column("Severity")
    table.add_column("Invariant")
    table.add_column("Message")
    for finding in findings:
        table.add_row(
            finding.rule_id,
            finding.severity.value.upper(),
            finding.invariant_name,
            finding.message,
        )
    console.print(table)
    console.print(f"Findings: [bold]{evaluation.finding_count}[/bold]")
    console.print(f"Policy violations: [bold]{evaluation.violating_finding_count}[/bold]")
    console.print(f"Policy status: [bold]{evaluation.status.value}[/bold]")

    if evaluation.status is PolicyStatus.failed:
        raise typer.Exit(code=1)


@policy_app.command("sarif")
def sarif_command(
    findings: Path,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write SARIF to this path instead of stdout."),
    ] = None,
) -> None:
    """Render a canonical ERPChaos findings document as SARIF 2.1.0."""

    try:
        document = FindingDocument.model_validate_json(findings.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid findings document:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    rendered = canonical_sarif_json(document.findings)
    if output is None:
        typer.echo(rendered, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    console.print(f"SARIF: [bold]{output}[/bold]")
