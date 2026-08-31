from pathlib import Path
from subprocess import CompletedProcess

import pytest

from erpchaos import github_action


def _file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text("example: true\n", encoding="utf-8")
    return path


def test_build_verify_cli_args(tmp_path: Path) -> None:
    contract = _file(tmp_path, "contract.yaml")
    state = _file(tmp_path, "state.yaml")

    args = github_action.build_cli_args(
        {"mode": "verify", "contract": str(contract), "state": str(state)}
    )

    assert args == ["verify", str(contract), str(state)]


def test_build_chaos_cli_args(tmp_path: Path) -> None:
    scenario = _file(tmp_path, "scenario.yaml")
    stream = _file(tmp_path, "stream.yaml")

    args = github_action.build_cli_args(
        {"mode": "chaos", "scenario": str(scenario), "stream": str(stream)}
    )

    assert args == ["chaos", "run", str(scenario), str(stream)]


def test_build_experiment_cli_args(tmp_path: Path) -> None:
    contract = _file(tmp_path, "contract.yaml")
    scenario = _file(tmp_path, "scenario.yaml")
    stream = _file(tmp_path, "stream.yaml")

    args = github_action.build_cli_args(
        {
            "mode": "experiment",
            "contract": str(contract),
            "scenario": str(scenario),
            "stream": str(stream),
        }
    )

    assert args == [
        "experiment",
        "run",
        str(contract),
        str(scenario),
        str(stream),
    ]


def test_action_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode must be one of"):
        github_action.build_cli_args({"mode": "random"})


def test_action_rejects_missing_required_input(tmp_path: Path) -> None:
    contract = _file(tmp_path, "contract.yaml")

    with pytest.raises(ValueError, match="state is required for verify mode"):
        github_action.build_cli_args({"mode": "verify", "contract": str(contract)})


def test_action_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ValueError, match="contract file does not exist"):
        github_action.build_cli_args(
            {"mode": "verify", "contract": str(missing), "state": str(missing)}
        )


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, "PASS"),
        (1, "BUSINESS_FAILURE"),
        (2, "INVALID_INPUT"),
        (3, "EXECUTION_ERROR"),
    ],
)
def test_exit_code_classification(code: int, expected: str) -> None:
    assert github_action.classify_exit_code(code) == expected


def test_business_failure_publishes_outputs_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = _file(tmp_path, "contract.yaml")
    state = _file(tmp_path, "state.yaml")
    output_file = tmp_path / "github-output.txt"
    summary_file = tmp_path / "summary.md"

    monkeypatch.setenv("ERPCHAOS_ACTION_MODE", "verify")
    monkeypatch.setenv("ERPCHAOS_ACTION_CONTRACT", str(contract))
    monkeypatch.setenv("ERPCHAOS_ACTION_STATE", str(state))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setattr(
        github_action.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "BRS 80/100\n", ""),
    )

    exit_code = github_action.main()

    assert exit_code == 1
    outputs = output_file.read_text(encoding="utf-8")
    summary = summary_file.read_text(encoding="utf-8")
    assert "status=BUSINESS_FAILURE" in outputs
    assert "exit-code=1" in outputs
    assert "`BUSINESS_FAILURE`" in summary
    assert "BRS 80/100" in summary


def test_invalid_action_input_is_distinguishable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_file = tmp_path / "github-output.txt"
    summary_file = tmp_path / "summary.md"

    monkeypatch.setenv("ERPCHAOS_ACTION_MODE", "verify")
    monkeypatch.delenv("ERPCHAOS_ACTION_CONTRACT", raising=False)
    monkeypatch.delenv("ERPCHAOS_ACTION_STATE", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    exit_code = github_action.main()

    assert exit_code == 2
    outputs = output_file.read_text(encoding="utf-8")
    summary = summary_file.read_text(encoding="utf-8")
    assert "status=INVALID_INPUT" in outputs
    assert "exit-code=2" in outputs
    assert "contract is required for verify mode" in summary
