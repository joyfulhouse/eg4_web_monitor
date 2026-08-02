"""Regression tests for local quality and tier-validation runners."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import call, patch

from tests import run_tests as quality_runner
from tests import validate_platinum_tier


REPO_ROOT = Path(__file__).resolve().parents[1]


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    """Build a minimal subprocess result for runner tests."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_install_uses_the_existing_test_requirements_file() -> None:
    """The installer resolves requirements beside run_tests.py."""
    with patch.object(quality_runner.subprocess, "run") as run:
        quality_runner.install_test_requirements()

    requirements = REPO_ROOT / "tests" / "requirements-test.txt"
    run.assert_called_once_with(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
        check=True,
    )


def test_lint_runner_invokes_canonical_ruff_checks() -> None:
    """Local lint parity includes both Ruff lint and format verification."""
    with patch.object(
        quality_runner.subprocess,
        "run",
        side_effect=[_completed(0), _completed(0)],
    ) as run:
        assert quality_runner.run_linting() == 0

    assert run.call_args_list == [
        call(
            [sys.executable, "-m", "ruff", "check", "."],
            cwd=REPO_ROOT,
            check=False,
        ),
        call(
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            cwd=REPO_ROOT,
            check=False,
        ),
    ]


def test_lint_runner_propagates_ruff_failure() -> None:
    """A missing or failing Ruff module must make the local runner fail."""
    with patch.object(
        quality_runner.subprocess, "run", return_value=_completed(1)
    ) as run:
        assert quality_runner.run_linting() == 1

    run.assert_called_once_with(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        check=False,
    )


def test_lint_runner_propagates_format_failure() -> None:
    """Formatting drift is a quality failure, not a successful lint run."""
    with patch.object(
        quality_runner.subprocess,
        "run",
        side_effect=[_completed(0), _completed(2)],
    ):
        assert quality_runner.run_linting() == 2


def test_test_runner_normalizes_signal_termination_to_failure() -> None:
    """A signal-killed pytest process must not become success via max(0, -N)."""
    with patch.object(quality_runner.subprocess, "run", return_value=_completed(-9)):
        assert quality_runner.run_tests() == 1


def test_platinum_strict_typing_fails_on_mypy_errors() -> None:
    """Configured strict typing is insufficient when the actual check fails."""
    with patch.object(
        validate_platinum_tier.subprocess,
        "run",
        return_value=_completed(1, stdout="coordinator.py:1: error: broken"),
    ):
        assert validate_platinum_tier.check_strict_typing() is False


def test_platinum_strict_typing_fails_when_mypy_cannot_run() -> None:
    """An unavailable executable cannot satisfy Platinum strict typing."""
    with patch.object(
        validate_platinum_tier.subprocess,
        "run",
        side_effect=OSError("cannot execute"),
    ):
        assert validate_platinum_tier.check_strict_typing() is False


def test_platinum_strict_typing_passes_only_on_zero_exit() -> None:
    """A successful mypy process remains a passing validation."""
    with patch.object(
        validate_platinum_tier.subprocess,
        "run",
        return_value=_completed(0),
    ) as run:
        assert validate_platinum_tier.check_strict_typing() is True

    run.assert_called_once_with(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            "tests/mypy.ini",
            "custom_components/eg4_web_monitor",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_pytest_config_contains_only_supported_ini_options() -> None:
    """rootdir is a CLI option and must not be placed in pytest.ini."""
    config = (REPO_ROOT / "tests" / "pytest.ini").read_text(encoding="utf-8")
    assert not re.search(r"^rootdir\s*=", config, flags=re.MULTILINE)


def test_documented_validation_scripts_exist() -> None:
    """Every validation command documented in maintained guidance is runnable."""
    sources = [
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "docs" / "DEVELOPMENT.md",
        REPO_ROOT / ".github" / "WORKFLOWS.md",
        REPO_ROOT / "tests" / "validate_platinum_tier.py",
    ]
    pattern = re.compile(r"(?:tests/)?(validate_[a-z_]+\.py)")

    referenced = {
        match.group(1)
        for source in sources
        for match in pattern.finditer(source.read_text(encoding="utf-8"))
    }

    assert referenced
    assert {
        name for name in referenced if not (REPO_ROOT / "tests" / name).exists()
    } == set()
