"""Keep CI's minimum and current HA environments explicit and blocking."""

from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("job_name", ["gold-test-coverage", "platinum-strict-typing"])
def test_ha_gates_cover_minimum_and_latest(job_name: str) -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/quality-validation.yml").read_text()
    )
    job = workflow["jobs"][job_name]
    assert not job.get("continue-on-error", False)
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["include"] == [
        {
            "ha": "minimum",
            "python": "3.13",
            "constraints": "tests/constraints-ha-minimum.txt",
        },
        {
            "ha": "latest",
            "python": "3.14",
            "constraints": "tests/constraints-ha-latest.txt",
        },
    ]
    steps = job["steps"]
    setup = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    assert setup["with"]["python-version"] == "${{ matrix.python }}"
    installs = "\n".join(step.get("run", "") for step in steps)
    assert "-c ${{ matrix.constraints }}" in installs


@pytest.mark.parametrize("target", ["minimum", "latest"])
def test_ha_constraints_pin_core_and_plugin(target: str) -> None:
    pins = (ROOT / f"tests/constraints-ha-{target}.txt").read_text().splitlines()
    pins = [line for line in pins if line and not line.startswith("#")]
    assert len(pins) == 2
    assert pins[0].startswith("homeassistant==")
    assert pins[1].startswith("pytest-homeassistant-custom-component==")


def test_auxiliary_ha_jobs_use_latest_environment() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/quality-validation.yml").read_text()
    )
    for name in ("platinum-comprehensive-tests", "platinum-validation-script"):
        steps = workflow["jobs"][name]["steps"]
        setup = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/setup-python@")
        )
        assert setup["with"]["python-version"] == "3.14"
        assert any(
            "-c tests/constraints-ha-latest.txt" in step.get("run", "")
            for step in steps
        )


def test_mypy_uses_the_active_python_version() -> None:
    config = (ROOT / "tests/mypy.ini").read_text()
    assert not re.search(r"^python_version\s*=", config, flags=re.MULTILINE)
