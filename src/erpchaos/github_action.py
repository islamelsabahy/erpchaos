from __future__ import annotations

from collections.abc import Mapping
import html
import os
from pathlib import Path
import subprocess
import sys


VALID_MODES = {"verify", "chaos", "experiment"}


def build_cli_args(values: Mapping[str, str]) -> list[str]:
    """Build a validated ERPChaos CLI invocation from GitHub Action inputs."""

    mode = values.get("mode", "").strip().lower()
    if mode not in VALID_MODES:
        allowed = ", ".join(sorted(VALID_MODES))
        raise ValueError(f"mode must be one of: {allowed}")

    if mode == "verify":
        contract = _required_file(values, "contract", mode)
        state = _required_file(values, "state", mode)
        return ["verify", str(contract), str(state)]

    if mode == "chaos":
        scenario = _required_file(values, "scenario", mode)
        stream = _required_file(values, "stream", mode)
        return ["chaos", "run", str(scenario), str(stream)]

    contract = _required_file(values, "contract", mode)
    scenario = _required_file(values, "scenario", mode)
    stream = _required_file(values, "stream", mode)
    return ["experiment", "run", str(contract), str(scenario), str(stream)]


def classify_exit_code(exit_code: int) -> str:
    if exit_code == 0:
        return "PASS"
    if exit_code == 1:
        return "BUSINESS_FAILURE"
    if exit_code == 2:
        return "INVALID_INPUT"
    return "EXECUTION_ERROR"


def main() -> int:
    values = {
        "mode": os.environ.get("ERPCHAOS_ACTION_MODE", ""),
        "contract": os.environ.get("ERPCHAOS_ACTION_CONTRACT", ""),
        "state": os.environ.get("ERPCHAOS_ACTION_STATE", ""),
        "scenario": os.environ.get("ERPCHAOS_ACTION_SCENARIO", ""),
        "stream": os.environ.get("ERPCHAOS_ACTION_STREAM", ""),
    }
    mode = values["mode"].strip().lower() or "unknown"

    try:
        cli_args = build_cli_args(values)
    except ValueError as exc:
        message = str(exc)
        print(f"ERPChaos Action input error: {message}", file=sys.stderr)
        _publish_result(mode, "INVALID_INPUT", 2, message)
        return 2

    completed = subprocess.run(
        [sys.executable, "-m", "erpchaos.cli", *cli_args],
        capture_output=True,
        text=True,
        check=False,
    )
    combined_output = _emit_cli_output(completed.stdout, completed.stderr)
    status = classify_exit_code(completed.returncode)
    _publish_result(mode, status, completed.returncode, combined_output)
    return completed.returncode


def _required_file(values: Mapping[str, str], name: str, mode: str) -> Path:
    raw = values.get(name, "").strip()
    if not raw:
        raise ValueError(f"{name} is required for {mode} mode")
    path = Path(raw)
    if not path.is_file():
        raise ValueError(f"{name} file does not exist: {path}")
    return path


def _emit_cli_output(stdout: str, stderr: str) -> str:
    chunks: list[str] = []
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
        chunks.append(stdout.rstrip())
    if stderr:
        print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
        chunks.append(stderr.rstrip())
    return "\n".join(chunk for chunk in chunks if chunk)


def _publish_result(mode: str, status: str, exit_code: int, output: str) -> None:
    _write_action_outputs(status, exit_code)
    _write_step_summary(mode, status, exit_code, output)


def _write_action_outputs(status: str, exit_code: int) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"status={status}\n")
        handle.write(f"exit-code={exit_code}\n")


def _write_step_summary(mode: str, status: str, exit_code: int, output: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    rendered_output = html.escape(output or "No CLI output.")
    summary = (
        "## ERPChaos Business Reliability Gate\n\n"
        f"- **Mode:** `{mode}`\n"
        f"- **Status:** `{status}`\n"
        f"- **Exit code:** `{exit_code}`\n\n"
        "<details><summary>ERPChaos output</summary>\n\n"
        f"<pre>{rendered_output}</pre>\n\n"
        "</details>\n"
    )
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(summary)


if __name__ == "__main__":
    raise SystemExit(main())
