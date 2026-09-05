"""Legacy list options honor defaults without hiding explicit user overrides."""

import json

import pytest

from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture

CASES = [
    (
        "content-banned-references",
        "banned",
        "content/banned-references-migration",
        [],
    ),
    (
        "agentskill-structure",
        "allowed_dirs",
        "agentskills/unreferenced-clean",
        ["assets", "evals", "references", "scripts"],
    ),
    (
        "claude-plugin-json-valid",
        "recommended-fields",
        "single-plugin/clean",
        ["description", "version", "author"],
    ),
]


def _lint(repo, rule, options):
    config = repo / ".skillsaw.yaml"
    config.write_text(json.dumps({"version": "0.20.0", "rules": {rule: options}}))
    result = run_cli(
        [
            "lint",
            repo,
            "--rule",
            rule,
            "--format",
            "json",
            "--verbose",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert rule in report["stats"]["rules_run"]
    assert not any(v["rule_id"] == "rule-execution-error" for v in report["violations"])
    return report["violations"]


@pytest.mark.parametrize("rule,option,fixture,default", CASES)
@pytest.mark.parametrize("value", [None, 123, False, "invalid", {"bad": "value"}])
def test_null_and_wrong_list_types_keep_default_checks(
    tmp_path, rule, option, fixture, default, value
):
    repo = copy_fixture(fixture, tmp_path)
    omitted = _lint(repo, rule, {})
    assert _lint(repo, rule, {option: default}) == omitted
    if rule == "agentskill-structure":
        assert [(v["file_path"], v["severity"]) for v in omitted] == [
            ("report-builder/tests", "warning")
        ]
    elif rule == "content-banned-references":
        assert len(omitted) == 5
        assert all(v["file_path"] == ".claude/skills/model-upgrade/SKILL.md" for v in omitted)
    else:
        assert omitted == []

    found = _lint(repo, rule, {option: value})
    config_warnings = [v for v in found if v["rule_id"] == "invalid-config"]
    assert len(config_warnings) == 1
    assert config_warnings[0]["severity"] == "warning"
    assert option in config_warnings[0]["message"]
    assert "expects list" in config_warnings[0]["message"]
    assert [v for v in found if v["rule_id"] != "invalid-config"] == omitted


def test_custom_banned_patterns_are_applied_and_empty_list_clears_them(tmp_path):
    repo = copy_fixture("content/banned-references-migration", tmp_path)
    rule = "content-banned-references"
    found = _lint(
        repo,
        rule,
        {
            "skip-builtins": True,
            "banned": [{"pattern": "model-upgrade", "message": "Review upgrades"}],
        },
    )
    assert [(v["rule_id"], v["file_path"], v["line"]) for v in found] == [(rule, "CLAUDE.md", 10)]
    assert "Review upgrades" in found[0]["message"]
    assert _lint(repo, rule, {"skip-builtins": True, "banned": []}) == []


def test_custom_allowed_directories_and_empty_override_are_applied(tmp_path):
    repo = copy_fixture("agentskills/unreferenced-clean", tmp_path)
    rule = "agentskill-structure"
    allowed = ["assets", "evals", "references", "scripts", "tests"]
    assert _lint(repo, rule, {"allowed_dirs": allowed}) == []
    found = _lint(repo, rule, {"allowed_dirs": []})
    assert {v["file_path"] for v in found} == {f"report-builder/{name}" for name in allowed}
    assert len(found) == len(allowed)
    assert all(v["rule_id"] == rule and v["severity"] == "warning" for v in found)


def test_custom_recommended_fields_and_empty_override_are_applied(tmp_path):
    repo = copy_fixture("single-plugin/clean", tmp_path)
    rule = "claude-plugin-json-valid"
    found = _lint(repo, rule, {"recommended-fields": ["repository"]})
    assert [(v["rule_id"], v["file_path"], v["message"]) for v in found] == [
        (rule, ".claude-plugin/plugin.json", "Missing recommended field 'repository'")
    ]
    assert _lint(repo, rule, {"recommended-fields": []}) == []
