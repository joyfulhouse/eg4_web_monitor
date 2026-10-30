"""Keep CI's minimum and current HA environments explicit and blocking."""

from importlib.metadata import version
import json
from pathlib import Path
import re

import homeassistant
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
            "python": "3.14",
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
def test_ha_constraints_pin_core_plugin_and_usb_dependencies(target: str) -> None:
    pins = (ROOT / f"tests/constraints-ha-{target}.txt").read_text().splitlines()
    pins = [line for line in pins if line and not line.startswith("#")]
    assert pins[0].startswith("homeassistant==")
    assert pins[1].startswith("pytest-homeassistant-custom-component==")
    assert len(pins) == 4
    assert re.fullmatch(r"aiousbwatcher==\S+", pins[2])
    assert re.fullmatch(r"serialx==\S+", pins[3])


@pytest.mark.parametrize("target", ["minimum", "latest"])
def test_usb_constraints_match_installed_home_assistant(target: str) -> None:
    constraints = ROOT / f"tests/constraints-ha-{target}.txt"
    pins = constraints.read_text().splitlines()
    ha_pin = next(
        line.removeprefix("homeassistant==")
        for line in pins
        if line.startswith("homeassistant==")
    )
    installed_ha = version("homeassistant")
    if ha_pin != installed_ha:
        pytest.skip(f"{target} pins HA {ha_pin}; installed HA is {installed_ha}")

    usb_manifest = Path(homeassistant.__file__).parent / "components/usb/manifest.json"
    requirements = json.loads(usb_manifest.read_text())["requirements"]
    usb_requirements = {
        requirement.split("==", maxsplit=1)[0]: requirement
        for requirement in requirements
        if requirement.startswith(("aiousbwatcher==", "serialx=="))
    }
    assert set(usb_requirements) == {"aiousbwatcher", "serialx"}
    constraint_usb_pins = {
        pin for pin in pins if pin.startswith(("aiousbwatcher==", "serialx=="))
    }
    assert constraint_usb_pins == set(usb_requirements.values())


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
