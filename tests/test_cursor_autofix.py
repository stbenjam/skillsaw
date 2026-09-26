"""Cursor's SAFE scalar repair must preserve authored YAML structure."""

import json

import pytest

from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.parametrize(
    "name",
    [
        "folded-strip",
        "literal-strip",
        "quoted-folded",
        "quoted-escaped",
        "anchored",
        "alias",
        "tagged",
    ],
)
def test_complex_always_apply_is_diagnostic_only(tmp_path, name):
    repo = copy_fixture("autofix/safe-idempotency", tmp_path)
    target = repo / ".cursor/rules" / f"complex-{name}.mdc"
    before = target.read_bytes()
    args = [str(repo), "--no-custom-rules", "--rule", "cursor-rules-valid"]

    def lint():
        result = run_cli(["lint", *args, "--format", "json", "-v"])
        assert result.returncode == 1, result.stdout + result.stderr
        findings = [
            finding
            for finding in json.loads(result.stdout)["violations"]
            if finding["file_path"].endswith(target.name)
        ]
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "cursor-rules-valid"
        assert findings[0]["message"].startswith("'alwaysApply' must be a boolean")
        assert findings[0]["fixable"] is False
        return findings

    findings = lint()
    for _ in range(2):
        result = run_cli(["fix", *args])
        assert result.returncode == 0, result.stdout + result.stderr
        assert target.read_bytes() == before
        assert lint() == findings
