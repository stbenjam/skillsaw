"""Bun hooks have the same download-and-execute checks as other runtimes."""

import json

import pytest

from skillsaw.rules.builtin.hooks.dangerous import dangerous_command_descriptions
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.parametrize(
    "command",
    ["bun run scripts/format.ts", "bun run lint", "/usr/local/bin/bun scripts/check.ts"],
)
def test_local_bun_commands_are_allowed(command):
    assert dangerous_command_descriptions(command) == []


def test_local_bun_hooks_cli(tmp_path):
    repo = copy_fixture("hooks/bun-local", tmp_path)
    result = run_cli(
        ["lint", str(repo), "--no-custom-rules", "--rule", "hooks-dangerous", "--format", "json"]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["violations"] == []


def test_downloaded_bun_hooks_cli(tmp_path):
    repo = copy_fixture("hooks/bun-download", tmp_path)
    result = run_cli(
        ["lint", str(repo), "--no-custom-rules", "--rule", "hooks-dangerous", "--format", "json"]
    )
    assert result.returncode == 1, result.stderr
    violations = json.loads(result.stdout)["violations"]
    assert len(violations) == 2
    assert all(v["severity"] == "error" for v in violations)
    assert all("downloads and executes remote code" in v["message"] for v in violations)
