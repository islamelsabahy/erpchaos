from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console

from erpchaos.effects import EffectMap
from erpchaos.engine import verify_contract
from erpchaos.events import EventStream
from erpchaos.evidence import (
    evidence_for_experiment,
    evidence_for_recovery,
    evidence_for_verification,
    load_evidence,
    verify_evidence,
    write_evidence,
)
from erpchaos.experiment import run_experiment
from erpchaos.faults import ChaosScenario
from erpchaos.lineage import EffectLineagePolicy
from erpchaos.models import BusinessReliabilityContract
from erpchaos.recovery import RecoveryContract, RecoveryScenario, run_recovery_experiment

evidence_app = typer.Typer(
    help="Generate and verify deterministic Business Reliability Evidence bundles.",
    no_args_is_help=True,
)
console = Console()


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise typer.BadParameter(f"Expected a YAML object in {path}")
    return data


def _optional_input_paths(
    base: dict[str, Path],
    *,
    effect_map: Path | None,
    lineage_policy: Path | None,
) -> dict[str, Path]:
    paths = dict(base)
    if effect_map is not None:
        paths["effect_map"] = effect_map
    if lineage_policy is not None:
        paths["lineage_policy"] = lineage_policy
    return paths


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


@evidence_app.command("generate-verify")
def evidence_generate_verify(contract: Path, state: Path, output: Path) -> None:
    """Run static BRC verification and write deterministic evidence."""

    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        transaction_state = _load_yaml(state)
        results = verify_contract(brc, transaction_state)
        evidence = evidence_for_verification(
            {"contract": contract, "state": state},
            results,
        )
        write_evidence(output, evidence)
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid evidence generation input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"Evidence: [bold]{output}[/bold]")
    if any(not result.passed for result in results):
        raise typer.Exit(code=1)


@evidence_app.command("generate-experiment")
def evidence_generate_experiment(
    contract: Path,
    scenario: Path,
    stream: Path,
    output: Path,
    effect_map: Annotated[
        Path | None,
        typer.Option("--effect-map", help="Optional Business Effect Ledger map YAML."),
    ] = None,
    lineage_policy: Annotated[
        Path | None,
        typer.Option("--lineage-policy", help="Optional compensation lineage policy YAML."),
    ] = None,
) -> None:
    """Run a chaos experiment and write deterministic evidence."""

    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        effects = EffectMap.model_validate(_load_yaml(effect_map)) if effect_map else None
        lineage = (
            EffectLineagePolicy.model_validate(_load_yaml(lineage_policy))
            if lineage_policy
            else None
        )
        result = run_experiment(brc, chaos_scenario, event_stream, effects, lineage)
        paths = _optional_input_paths(
            {"contract": contract, "scenario": scenario, "stream": stream},
            effect_map=effect_map,
            lineage_policy=lineage_policy,
        )
        write_evidence(output, evidence_for_experiment(paths, result))
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid evidence generation input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"Evidence: [bold]{output}[/bold]")
    if not result.passed:
        raise typer.Exit(code=1)


@evidence_app.command("generate-recovery")
def evidence_generate_recovery(
    contract: Path,
    scenario: Path,
    stream: Path,
    recovery_contract: Path,
    recovery_scenario: Path,
    output: Path,
    effect_map: Annotated[
        Path | None,
        typer.Option("--effect-map", help="Optional Business Effect Ledger map YAML."),
    ] = None,
    lineage_policy: Annotated[
        Path | None,
        typer.Option("--lineage-policy", help="Optional compensation lineage policy YAML."),
    ] = None,
) -> None:
    """Run deterministic recovery and write evidence."""

    try:
        brc = BusinessReliabilityContract.model_validate(_load_yaml(contract))
        chaos_scenario = ChaosScenario.model_validate(_load_yaml(scenario))
        event_stream = EventStream.model_validate(_load_yaml(stream))
        recovery_brc = RecoveryContract.model_validate(_load_yaml(recovery_contract))
        recovery = RecoveryScenario.model_validate(_load_yaml(recovery_scenario))
        effects = EffectMap.model_validate(_load_yaml(effect_map)) if effect_map else None
        lineage = (
            EffectLineagePolicy.model_validate(_load_yaml(lineage_policy))
            if lineage_policy
            else None
        )
        result = run_recovery_experiment(
            brc,
            chaos_scenario,
            event_stream,
            recovery_brc,
            recovery,
            effects,
            lineage,
        )
        paths = _optional_input_paths(
            {
                "contract": contract,
                "scenario": scenario,
                "stream": stream,
                "recovery_contract": recovery_contract,
                "recovery_scenario": recovery_scenario,
            },
            effect_map=effect_map,
            lineage_policy=lineage_policy,
        )
        write_evidence(output, evidence_for_recovery(paths, result))
    except (OSError, ValidationError, ValueError) as exc:
        console.print(f"[red]Invalid evidence generation input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(f"Evidence: [bold]{output}[/bold]")
    if not result.passed:
        raise typer.Exit(code=1)
