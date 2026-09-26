"""Upgrade guidance for retired rule IDs in the explain CLI."""

import shutil
from pathlib import Path

import pytest

from skillsaw.plugins import PluginInfo
from skillsaw.rule import Rule, Severity
from tests.cli_runner import run_cli


@pytest.fixture
def repository(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "removed-docs-command"
    return Path(shutil.copytree(fixture, tmp_path / "repository"))


@pytest.mark.parametrize(
    ("rule_id", "replacement"),
    [
        ("content-critical-position", None),
        ("content-actionability-score", None),
        ("skill-frontmatter", "agentskill-valid"),
    ],
)
def test_explain_names_removed_rules(repository, rule_id, replacement):
    result = run_cli(["explain", rule_id, repository, "--no-pager"])

    assert result.returncode == 1
    assert f"Rule '{rule_id}' was removed in 0.21.0" in result.stderr
    assert "Unknown rule" not in result.stderr
    assert "Did you mean" not in result.stderr
    assert result.stdout == ""
    if replacement:
        assert f"use '{replacement}' instead" in result.stderr
    else:
        assert "instead" not in result.stderr


def test_explain_unknown_rule_keeps_typo_suggestions(repository):
    result = run_cli(["explain", "content-weak-langage", repository, "--no-pager"])

    assert result.returncode == 1
    assert "Unknown rule 'content-weak-langage'" in result.stderr
    assert "Did you mean: content-weak-language" in result.stderr
    assert "removed" not in result.stderr


def test_explain_installed_plugin_can_reuse_removed_id(repository, monkeypatch):
    class ReplacementRule(Rule):
        @property
        def rule_id(self):
            return "skill-frontmatter"

        @property
        def description(self):
            return "Validate organization-specific skill metadata"

        def default_severity(self):
            return Severity.WARNING

        def check(self, context):
            return []

    plugin = PluginInfo("organization", "organization.rules", rule_classes=[ReplacementRule])
    monkeypatch.setattr("skillsaw.plugins.load_plugins", lambda **kwargs: [plugin])
    result = run_cli(["explain", "skill-frontmatter", repository, "--no-pager"])

    assert result.returncode == 0, result.stderr
    assert "plugin: organization" in result.stdout
    assert "Validate organization-specific skill metadata" in result.stdout
    assert "removed" not in result.stderr


@pytest.mark.parametrize("command", ["lint", "fix"])
def test_skip_installed_plugin_reusing_removed_id(repository, monkeypatch, command):
    checked = []

    class ReplacementRule(Rule):
        default_enabled = True

        @property
        def rule_id(self):
            return "skill-frontmatter"

        @property
        def description(self):
            return "Validate organization-specific skill metadata"

        def default_severity(self):
            return Severity.WARNING

        def check(self, context):
            checked.append(context.root_path)
            return [self.violation("Organization metadata missing", file_path=context.root_path)]

    plugin = PluginInfo("organization", "organization.rules", rule_classes=[ReplacementRule])
    monkeypatch.setattr("skillsaw.plugins.load_plugins", lambda **kwargs: [plugin])

    normal = run_cli([command, repository])
    assert normal.returncode == 0, normal.stderr
    assert checked
    checked.clear()

    skipped = run_cli([command, repository, "--skip-rule", "skill-frontmatter"])
    assert skipped.returncode == 0, skipped.stderr
    assert checked == []
    assert "has no effect" not in skipped.stderr
    assert "was removed" not in skipped.stderr

    unloaded = run_cli([command, repository, "--skip-rule", "skill-frontmatter", "--no-plugins"])
    assert unloaded.returncode == 0, unloaded.stderr
    assert unloaded.stderr.count("--skip-rule skill-frontmatter has no effect") == 1


@pytest.mark.parametrize("command", ["lint", "fix"])
def test_removed_skip_warns_once_across_paths(repository, tmp_path, command):
    second = Path(shutil.copytree(repository, tmp_path / "second"))
    result = run_cli([command, repository, second, "--skip-rule", "skill-frontmatter"])

    assert result.returncode == 0, result.stderr
    assert result.stderr.count("--skip-rule skill-frontmatter has no effect") == 1
