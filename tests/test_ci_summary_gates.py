"""Required summary checks must fail closed, including skipped predecessors."""

import json
from pathlib import Path

import pytest
import yaml

from scripts.check_ci_dependencies import main, unsuccessful_dependencies


@pytest.mark.parametrize("result", ["failure", "skipped", "cancelled", "unknown", None])
def test_non_success_result_blocks_summary(result):
    assert unsuccessful_dependencies(
        {"tests": {"result": result}, "lint": {"result": "success"}}
    ) == ["tests"]


def test_empty_or_missing_results_fail_closed():
    assert unsuccessful_dependencies({})
    assert unsuccessful_dependencies({"tests": {}}) == ["tests"]


@pytest.mark.parametrize("result,expected", [("success", 0), ("skipped", 1)])
def test_summary_command_exit_status(monkeypatch, result, expected):
    monkeypatch.setenv("NEEDS_JSON", json.dumps({"tests": {"result": result}}))
    assert main() == expected


@pytest.mark.parametrize("tier", ["bronze", "silver", "gold", "platinum"])
def test_required_summary_runs_even_after_failed_dependency(tier):
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (root / ".github/workflows/quality-validation.yml").read_text()
    )
    job = workflow["jobs"][f"{tier}-summary"]
    assert job["if"] == "${{ always() }}"
    assert not job.get("continue-on-error", False)
    guard = next(
        step
        for step in job["steps"]
        if step.get("run") == "python scripts/check_ci_dependencies.py"
    )
    assert guard["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert not guard.get("continue-on-error", False)
