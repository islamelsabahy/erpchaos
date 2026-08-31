from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from erpchaos.evidence import load_evidence, verify_evidence

evidence_app = typer.Typer(
    help="Verify deterministic Business Reliability Evidence bundles.",
    no_args_is_help=True,
)
console = Console()


@evidence_app.command("verify")
def evidence_verify(path: Path) -> None:
    """Verify the self-digest of one ERPChaos evidence bundle."""

    try:
        evidence = load_evidence(path)
    except (OSError, ValueError, ValidationError) as exc:
        console.print(f"[red]Invalid evidence input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if not verify_evidence(evidence):
        console.print("Evidence verification: [bold]FAIL[/bold]")
        console.print(f"Mode: [bold]{evidence.mode}[/bold]")
        console.print(f"Status: [bold]{evidence.status}[/bold]")
        raise typer.Exit(code=1)

    console.print("Evidence verification: [bold]PASS[/bold]")
    console.print(f"Mode: [bold]{evidence.mode}[/bold]")
    console.print(f"Status: [bold]{evidence.status}[/bold]")
    console.print(f"Digest: [bold]{evidence.evidence_digest}[/bold]")
