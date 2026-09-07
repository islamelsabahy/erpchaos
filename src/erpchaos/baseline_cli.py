from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console

from erpchaos.baseline import (
    BaselineExceptionDocument,
    ReliabilityBaseline,
    canonical_baseline_json,
    capture_baseline,
    compare_baseline,
)
from erpchaos.policy import FindingDocument

baseline_app = typer.Typer(
    help="Capture and compare deterministic business reliability baselines.",
    no_args_is_help=True,
)
console = Console()


def _load_findings(path: Path) -> FindingDocument:
    return FindingDocument.model_validate_json(path.read_text(encoding="utf-8"))


@baseline_app.command("capture")
def capture_command(
    findings: Path,
    name: Annotated[str, typer.Option("--name", help="Stable baseline name.")],
    output: Annotated[Path, typer.Option("--output", help="Write canonical baseline JSON.")],
) -> None:
    """Capture the current findings as a canonical reliability baseline."""
    try:
        document = _load_findings(findings)
        baseline = capture_baseline(name, document.findings)
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid baseline input:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_baseline_json(baseline), encoding="utf-8")
    console.print(f"Baseline: [bold]{output}[/bold]")


@baseline_app.command("compare")
def compare_command(
    baseline: Path,
    findings: Path,
    evaluation_date: Annotated[
        date,
        typer.Option("--evaluation-date", help="Explicit deterministic YYYY-MM-DD boundary."),
    ],
    exceptions: Annotated[
        Path | None,
        typer.Option("--exceptions", help="Optional exact-fingerprint exception document."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write canonical comparison JSON."),
    ] = None,
) -> None:
    """Classify current findings as known, new, resolved, or regressed."""
    try:
        baseline_model = ReliabilityBaseline.model_validate_json(
            baseline.read_text(encoding="utf-8")
        )
        current = _load_findings(findings)
        exception_model = (
            BaselineExceptionDocument.model_validate_json(exceptions.read_text(encoding="utf-8"))
            if exceptions is not None
            else None
        )
        report = compare_baseline(
            baseline_model,
            current.findings,
            evaluation_date=evaluation_date,
            exceptions=exception_model,
        )
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid baseline comparison input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    rendered = canonical_baseline_json(report)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"Comparison: [bold]{output}[/bold]")

    if report.status == "FAIL":
        raise typer.Exit(code=1)
