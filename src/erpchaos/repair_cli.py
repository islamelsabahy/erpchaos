from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from erpchaos.effects import EffectMap
from erpchaos.evidence import build_evidence, write_evidence
from erpchaos.events import EventStream
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import RecoveryContract
from erpchaos.repair import RepairCatalog, synthesize_repair_plan

repair_app = typer.Typer(
    help="Synthesize minimal deterministic repair plans from bounded compensation catalogs.",
    no_args_is_help=True,
)
console = Console()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Expected a YAML object in {path}")
    return data


@repair_app.command("synthesize")
def repair_synthesize(
    contract: Path,
    scenario: Path,
    stream: Path,
    recovery_contract: Path,
    catalog: Path,
    effect_map: Annotated[
        Path | None,
        typer.Option("--effect-map", help="Optional Business Effect Ledger map YAML."),
    ] = None,
    lineage_policy: Annotated[
        Path | None,
        typer.Option("--lineage-policy", help="Optional compensation lineage policy YAML."),
    ] = None,
    evidence_output: Annotated[
        Path | None,
        typer.Option("--evidence", help="Write deterministic Business Reliability Evidence JSON."),
    ] = None,
) -> None:
    """Synthesize the first minimal repair plan that restores recovery invariants."""
    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        recovery_brc = RecoveryContract.model_validate(_load_yaml(recovery_contract))
        repair_catalog = RepairCatalog.model_validate(_load_yaml(catalog))
        effects = EffectMap.model_validate(_load_yaml(effect_map)) if effect_map else None
        lineage = (
            EffectLineagePolicy.model_validate(_load_yaml(lineage_policy))
            if lineage_policy
            else None
        )
        result = synthesize_repair_plan(
            brc,
            chaos_scenario,
            event_stream,
            recovery_brc,
            repair_catalog,
            effects,
            lineage,
        )
    except (ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid repair input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    table = Table(title=f"ERPChaos Minimal Repair — {repair_catalog.name}")
    table.add_column("Step", justify="right")
    table.add_column("Candidate")
    table.add_column("Event ID")
    table.add_column("Event Type")
    for step, (candidate_name, event) in enumerate(
        zip(result.selected_candidate_names, result.generated_events, strict=True),
        start=1,
    ):
        table.add_row(str(step), candidate_name, event.event_id, event.event_type)
    console.print(table)

    invariant_table = Table(title=f"Repair Contract — {recovery_brc.name}")
    invariant_table.add_column("Invariant")
    invariant_table.add_column("Result")
    invariant_table.add_column("Severity")
    invariant_table.add_column("Actual")
    invariant_table.add_column("Expected")
    for invariant in result.invariant_results:
        invariant_table.add_row(
            invariant.name,
            "PASS" if invariant.passed else "FAIL",
            invariant.severity.upper(),
            repr(invariant.actual),
            repr(invariant.expected),
        )
    console.print(invariant_table)

    plan_length = "none" if result.plan_length is None else str(result.plan_length)
    console.print(f"Repair Status: [bold]{result.status.value}[/bold]")
    console.print(f"Searched Plans: [bold]{result.searched_plan_count}[/bold]")
    console.print(f"Selected Plan Length: [bold]{plan_length}[/bold]")
    console.print(f"Recovery Reliability Score: [bold]{result.score}/100[/bold]")

    if evidence_output is not None:
        input_paths = {
            "contract": contract,
            "scenario": scenario,
            "stream": stream,
            "recovery_contract": recovery_contract,
            "catalog": catalog,
        }
        if effect_map is not None:
            input_paths["effect_map"] = effect_map
        if lineage_policy is not None:
            input_paths["lineage_policy"] = lineage_policy
        evidence = build_evidence(
            mode="repair",
            status=result.status.value,
            input_paths=input_paths,
            result={
                "score": result.score,
                "searched_plan_count": result.searched_plan_count,
                "selected_candidate_names": result.selected_candidate_names,
                "plan_length": result.plan_length,
            },
            invariants=result.invariant_results,
        )
        write_evidence(evidence_output, evidence)
        console.print(f"Evidence: [bold]{evidence_output}[/bold]")

    if not result.passed:
        raise typer.Exit(code=1)
