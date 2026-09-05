"""Unknown Grok events do not invalidate recognized hook configuration."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import GrokHooksBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture

RULE = "grok-hooks-valid"
FILE = ".grok/hooks/events.json"


def fixture(tmp_path, name):
    repo = copy_fixture(f"grok/hooks-events/{name}", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(GrokHooksBlock)
    assert [str(b.path.relative_to(repo)) for b in blocks] == [FILE]
    return repo, blocks[0]


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


def test_unknown_values_emit_only_event_advisories(tmp_path):
    repo, _ = fixture(tmp_path, "unknown")
    code, findings = lint(repo)
    assert code == 0
    assert len(findings) == 4
    assert {(v["rule_id"], v["file_path"], v["severity"]) for v in findings} == {
        (RULE, FILE, "warning")
    }
    assert {v["message"] for v in findings} == {
        f"Unknown hook event '{event}'"
        for event in ("FutureReady", "FutureGroup", "FutureHandler", "FutureCommand")
    }


def test_same_wrong_value_under_native_event_remains_fatal(tmp_path):
    repo, _ = fixture(tmp_path, "known-invalid")
    code, findings = lint(repo)
    assert code == 1
    assert len(findings) == 1
    assert (findings[0]["rule_id"], findings[0]["file_path"], findings[0]["severity"]) == (
        RULE,
        FILE,
        "error",
    )
    assert findings[0]["message"] == "Hook event 'PreToolUse' must be an array of matcher groups"


@pytest.mark.parametrize("event", ["FutureReady", "FutureGroup", "FutureHandler"])
def test_extra_event_opt_in_enables_descendant_type_checks(tmp_path, event):
    repo, _ = fixture(tmp_path, "unknown")
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    extra-events: [{event}]\n")
    code, findings = lint(repo)
    assert code == 1
    assert len(findings) == 4
    errors = [v for v in findings if v["severity"] == "error"]
    assert len(errors) == 1
    assert errors[0]["file_path"] == FILE
    assert event in errors[0]["message"]
    assert sum(v["severity"] == "warning" for v in findings) == 3


def test_shared_inventory_still_sees_unknown_event_commands(tmp_path):
    repo, block = fixture(tmp_path, "unknown")
    (repo / ".skillsaw.yaml").write_text(
        'version: "0.20.0"\nrules:\n  hooks-prohibited:\n    enabled: true\n'
    )
    commands = [
        h.command
        for groups in block.events.values()
        for g in groups
        for h in g.handlers
        if isinstance(h.command, str)
    ]
    assert commands == ["/audit/recognized", "/audit/future"]
    code, findings = lint(repo)
    assert code == 1
    policy = [v for v in findings if v["rule_id"] == "hooks-prohibited"]
    assert len(policy) == 2
    assert all(v["file_path"] == FILE for v in policy)
    for command in commands:
        assert sum(command in v["message"] for v in policy) == 1
