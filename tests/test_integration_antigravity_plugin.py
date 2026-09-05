"""Static CLI regressions for the Antigravity manifest's own parser."""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import AntigravityPluginConfigNode
from tests.antigravity._helpers import copy_fixture
from tests.cli_runner import run_cli

RULE = "antigravity-plugin-json-valid"
MANIFEST = ".agents/plugins/berth-tools/plugin.json"


def lint(repo):
    result = run_cli(
        [
            "lint",
            str(repo),
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            "--format",
            "json",
            "--verbose",
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert RULE in report["stats"]["rules_run"]
    return result.returncode, report["violations"]


def fixture(tmp_path, name):
    repo = copy_fixture(f"antigravity/plugin-decoder/{name}", tmp_path)
    assert [
        str(n.path.relative_to(repo))
        for n in RepositoryContext(repo).lint_tree.find(AntigravityPluginConfigNode)
    ] == [MANIFEST]
    return repo


def test_default_lint_accepts_duplicate_unknown_metadata_and_exact_case(tmp_path):
    repo = fixture(tmp_path, "accepted")
    assert lint(repo) == (0, [])


@pytest.mark.parametrize(
    "name,problem",
    [
        ("duplicate-known", "duplicate JSON object key"),
        ("bad-unicode", "invalid Unicode surrogate"),
    ],
)
@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_native_manifest_rejections_use_primary_configured_severity(
    tmp_path, name, problem, severity
):
    repo = fixture(tmp_path, name)
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    severity: {severity}\n")
    code, found = lint(repo)
    assert code == (1 if severity == "error" else 0)
    assert len(found) == 1
    assert (found[0]["rule_id"], found[0]["file_path"], found[0]["severity"]) == (
        RULE,
        MANIFEST,
        severity,
    )
    assert problem in found[0]["message"]
    assert "directory is not a plugin" in found[0]["message"]


def test_capitalized_installer_name_keeps_runtime_fallback_advice(tmp_path):
    repo = fixture(tmp_path, "upper-name")
    code, found = lint(repo)
    assert code == 0
    assert len(found) == 1
    assert (found[0]["rule_id"], found[0]["file_path"], found[0]["severity"]) == (
        RULE,
        MANIFEST,
        "info",
    )
    assert "discovery falls back to the directory name" in found[0]["message"]
    assert "canonical 'name'" in found[0]["message"]
    assert "refuses" not in found[0]["message"]
