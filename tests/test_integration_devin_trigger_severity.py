"""Partly recognized Devin triggers retain a working invocation route."""

import json
from pathlib import Path

import pytest

from tests.cli_runner import run_cli
from tests.test_autofix import copy_fixture


@pytest.mark.parametrize("severity", [None, "info", "error"])
def test_devin_trigger_severity_and_override(tmp_path, severity):
    repo = copy_fixture("devin/trigger-severity", tmp_path)
    config = repo / ".skillsaw.yaml"
    settings = "{}" if severity is None else f"{{severity: {severity}}}"
    config.write_text(f'version: "0.20.0"\nrules:\n  devin-skill-valid: {settings}\n')
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            "devin-skill-valid",
            "--format",
            "json",
            "-v",
            "--no-custom-rules",
            "--no-plugins",
        ]
    )
    assert result.returncode == (0 if severity == "info" else 1), result.stderr
    report = json.loads(result.stdout)
    assert "devin-skill-valid" in report["stats"]["rules_run"]
    findings = [item for item in report["violations"] if item["rule_id"] == "devin-skill-valid"]
    assert len(findings) == 4
    by_skill = {Path(item["file_path"]).parent.name: item for item in findings}
    assert {name: item["severity"] for name, item in by_skill.items()} == {
        "partial": severity or "warning",
        "unknown": severity or "error",
        "empty": severity or "error",
        "malformed": severity or "error",
    }
    assert all(item["line"] == 3 for item in findings)
    assert "ignores unknown" in by_skill["partial"]["message"]
    assert "must list only" in by_skill["unknown"]["message"]
    assert "must list only" in by_skill["malformed"]["message"]
    assert "non-empty list" in by_skill["empty"]["message"]
