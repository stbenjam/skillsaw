"""Grok's unsigned timeout decoder distinguishes literal -0 from 0."""

import json
import math

import pytest

from skillsaw.blocks import GrokHooksBlock, HooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.grok import GrokHooksValidRule
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.parametrize(
    "token,accepted",
    [
        ("0", True),
        ("-0", False),
        ("0.0", False),
        ("-0.0", False),
        ("0e0", False),
        ("1", True),
        ("null", True),
        ("true", False),
        ("18446744073709551615", True),
        ("18446744073709551616", False),
        ('-0, "timeout": 0', True),
        ('0, "timeout": -0', False),
    ],
)
def test_timeout_tokens_keep_the_native_acceptance_boundary(tmp_path, token, accepted):
    repo = copy_fixture("grok/hook-numbers/zero", tmp_path)
    path = repo / ".grok/hooks/numbers.json"
    path.write_text(path.read_text().replace('"timeout": 0', '"timeout": ' + token))
    found = GrokHooksValidRule().check(RepositoryContext(repo))
    assert len(found) == (0 if accepted else 1)
    if not accepted:
        assert found[0].file_path == path
        assert "'timeout' must be" in found[0].message
        assert found[0].severity.value == "error"


def test_negative_zero_preservation_is_local_to_grok(tmp_path):
    repo = copy_fixture("grok/hook-numbers/negative-zero", tmp_path)
    path = repo / ".grok/hooks/numbers.json"
    grok = GrokHooksBlock(path=path).raw_data["hooks"]["PreToolUse"][0]["hooks"][0]
    shared = HooksBlock(path=path).raw_data["hooks"]["PreToolUse"][0]["hooks"][0]
    assert type(grok["timeout"]) is float
    assert math.copysign(1, grok["timeout"]) == -1
    assert type(shared["timeout"]) is int
    assert shared["timeout"] == 0


def test_negative_zero_text_inside_a_command_is_unchanged(tmp_path):
    repo = copy_fixture("grok/hook-numbers/zero", tmp_path)
    path = repo / ".grok/hooks/numbers.json"
    path.write_text(path.read_text().replace("/audit/inspect-only", "/audit/inspect-only -0"))
    block = RepositoryContext(repo).lint_tree.find(GrokHooksBlock)[0]
    assert block.events["PreToolUse"][0].handlers[0].command == "/audit/inspect-only -0"
    assert GrokHooksValidRule().check(RepositoryContext(repo)) == []


@pytest.mark.parametrize("fixture,expected_exit", [("zero", 0), ("negative-zero", 1)])
def test_default_cli_reports_only_the_invalid_literal_timeout(tmp_path, fixture, expected_exit):
    repo = copy_fixture(f"grok/hook-numbers/{fixture}", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(GrokHooksBlock)
    assert [str(b.path.relative_to(repo)) for b in blocks] == [".grok/hooks/numbers.json"]
    assert blocks[0].events["PreToolUse"][0].handlers[0].command == "/audit/inspect-only"
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
    assert result.returncode == expected_exit, result.stderr
    report = json.loads(result.stdout)
    assert "grok-hooks-valid" in report["stats"]["rules_run"]
    assert len(report["violations"]) == expected_exit
    if expected_exit:
        finding = report["violations"][0]
        assert (finding["rule_id"], finding["file_path"], finding["severity"]) == (
            "grok-hooks-valid",
            ".grok/hooks/numbers.json",
            "error",
        )
        assert "'timeout' must be a non-negative integer, got -0.0" in finding["message"]


def test_invalid_numeric_token_does_not_hide_shared_command_inventory(tmp_path):
    repo = copy_fixture("grok/hook-numbers/negative-zero", tmp_path)
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            "hooks-prohibited",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            "--format",
            "json",
        ]
    )
    assert result.returncode == 1, result.stderr
    found = json.loads(result.stdout)["violations"]
    assert len(found) == 1
    assert found[0]["rule_id"] == "hooks-prohibited"
    assert found[0]["file_path"] == ".grok/hooks/numbers.json"
    assert "/audit/inspect-only" in found[0]["message"]
