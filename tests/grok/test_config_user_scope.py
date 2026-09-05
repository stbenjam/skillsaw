"""The actual user file keeps validation without project-only advice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.blocks import GrokConfigBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli
from tests.grok._helpers import copy_fixture


@pytest.mark.parametrize("override", [None, "", "absolute", "relative", "symlink"])
def test_user_scope_identity_preserves_config_and_servers(tmp_path, monkeypatch, override):
    repo = copy_fixture("grok/config-user-scope", tmp_path)
    monkeypatch.setenv("HOME", str(repo))
    monkeypatch.setenv("USERPROFILE", str(repo))
    monkeypatch.chdir(repo)
    monkeypatch.delenv("GROK_HOME", raising=False)
    if override == "symlink":
        alias = tmp_path / "profile-alias"
        alias.symlink_to(repo / ".grok", target_is_directory=True)
        monkeypatch.setenv("GROK_HOME", str(alias))
    elif override is not None:
        monkeypatch.setenv(
            "GROK_HOME",
            {"": "", "absolute": str(repo / ".grok"), "relative": ".grok"}[override],
        )
    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert len(blocks) == 1
    assert blocks[0].is_user_config
    assert blocks[0].raw_data["ui"] == {"vim_mode": True}
    assert [server.name for server in blocks[0].servers] == ["canary"]
    result = run_cli(
        [
            "lint",
            repo,
            "--rule",
            "grok-config-project-scope",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []


@pytest.mark.parametrize("override", [False, True])
def test_same_file_away_from_user_home_remains_project_scoped(tmp_path, monkeypatch, override):
    repo = copy_fixture("grok/config-user-scope", tmp_path)
    home = tmp_path / "separate-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(repo if override else home))
    monkeypatch.setenv("USERPROFILE", str(repo if override else home))
    monkeypatch.delenv("GROK_HOME", raising=False)
    if override:
        # An explicit override means even HOME/.grok is a project candidate.
        monkeypatch.setenv("GROK_HOME", str(home / ".grok"))
    blocks = RepositoryContext(repo).lint_tree.find(GrokConfigBlock)
    assert len(blocks) == 1
    assert not blocks[0].is_user_config
    result = run_cli(
        [
            "lint",
            repo,
            "--rule",
            "grok-config-project-scope",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    findings = json.loads(result.stdout)["violations"]
    assert len(findings) == 1
    assert findings[0]["message"] == "[compat], [ui] are ignored in a project config.toml"


@pytest.mark.parametrize(
    "body, expected, exit_code, severity",
    [
        ("[ui]\nvim_mode = true\n[mcp_servers.bad]\ncommand = 42\n", "command", 0, "warning"),
        ("[ui]\nvim_mode = [\n", "TOML", 1, "error"),
    ],
)
def test_user_file_still_receives_config_validation(
    tmp_path, monkeypatch, body, expected, exit_code, severity
):
    repo = copy_fixture("grok/config-user-scope", tmp_path)
    path = repo / ".grok/config.toml"
    path.write_text(body)
    monkeypatch.setenv("GROK_HOME", str(path.parent))
    result = run_cli(
        [
            "lint",
            repo,
            "--rule",
            "grok-config-valid",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    findings = json.loads(result.stdout)["violations"]
    assert len(findings) == 1
    assert expected in findings[0]["message"]
    assert findings[0]["severity"] == severity
    assert Path(findings[0]["file_path"]).name == "config.toml"
