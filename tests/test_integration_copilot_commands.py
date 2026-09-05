"""VS Code command alternatives follow the schema and released normalizer."""

import json

import pytest

from tests.cli_runner import run_cli
from tests.test_autofix import copy_fixture


@pytest.mark.parametrize("case,expected_code", [("valid", 0), ("invalid", 1)])
def test_copilot_command_alternatives(tmp_path, case, expected_code):
    repo = copy_fixture(f"copilot/command-alternatives/{case}", tmp_path)
    result = run_cli(["lint", str(repo), "--rule", "copilot-agent-valid", "--format", "json", "-v"])
    assert result.returncode == expected_code, result.stderr
    report = json.loads(result.stdout)
    assert "copilot-agent-valid" in report["stats"]["rules_run"]
    assert report["stats"]["repo_types"] == ["copilot"]
    findings = report["violations"]
    if case == "valid":
        assert findings == []
    else:
        assert [(item["line"], item["severity"]) for item in findings] == [
            (7, "error"),
            (10, "error"),
            (11, "error"),
        ]
        assert "no non-empty command" in findings[0]["message"]
        assert "must be a string" in findings[1]["message"]
        assert "invalid type 'prompt'" in findings[2]["message"]
        assert all(item["file_path"] == ".github/agents/review.agent.md" for item in findings)
