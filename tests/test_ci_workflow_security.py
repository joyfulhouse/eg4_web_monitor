"""Quality CI cannot silently regain write credentials or floating executables."""

from pathlib import Path
import re

import yaml


def test_quality_workflow_uses_read_only_pinned_tools():
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/quality-validation.yml"
        ).read_text()
    )
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job.get("permissions", workflow["permissions"]) == {"contents": "read"}
        for step in job.get("steps", []):
            assert "astral.sh/uv/install.sh" not in step.get("run", "")
            if action := step.get("uses"):
                assert re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", action)
                if action.startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False
                if action.startswith("astral-sh/setup-uv@"):
                    assert re.fullmatch(r"\d+\.\d+\.\d+", step["with"]["version"])
