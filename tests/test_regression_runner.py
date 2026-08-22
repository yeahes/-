"""Contract tests for the unified regression command."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python.exe"
RUNNER = ROOT / "scripts" / "run_regression.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), "-X", "utf8", str(RUNNER), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_runner_lists_stable_check_slugs() -> None:
    result = _run("--list")
    assert result.returncode == 0
    assert "stable-run-state\tstable run state" in result.stdout
    assert "golden-subtitle-evaluation\tgolden subtitle evaluation" in result.stdout
    assert "syntax-check\tsyntax check" in result.stdout


def test_runner_rejects_unknown_only_target() -> None:
    result = _run("--only", "does-not-exist")
    assert result.returncode == 2
    assert "Unknown checks: does-not-exist" in result.stderr


def test_runner_can_execute_one_named_check() -> None:
    result = _run("--profile", "fast", "--only", "syntax-check", "--fail-fast")
    assert result.returncode == 0
    assert "checks=1" in result.stdout
    assert "syntax check: PASS" in result.stdout


if __name__ == "__main__":
    test_runner_lists_stable_check_slugs()
    test_runner_rejects_unknown_only_target()
    test_runner_can_execute_one_named_check()
    print("Regression runner contract tests passed.")
