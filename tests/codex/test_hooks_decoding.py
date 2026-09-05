"""Hook file boundaries from Codex's released configuration deserializer."""

import json

from skillsaw.blocks import CodexHooksBlock
from skillsaw.context import RepositoryContext
from tests.cli_runner import run_cli

from ._helpers import copy_fixture


def test_json_wrapper_refusals_are_reported_without_hiding_commands(tmp_path):
    repo = copy_fixture("codex/hooks-wrapper", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(CodexHooksBlock)
    assert {
        block.path.relative_to(repo).parts[0]: [
            handler.command
            for entries in block.events.values()
            for entry in entries
            for handler in entry.handlers
        ]
        for block in blocks
    } == {
        name: ["printf ready"]
        for name in ("unknown", "description-list", "description-null", "description-string")
    }
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            "codex-hooks-valid",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    findings = report["violations"]
    assert len(findings) == 2, findings
    assert {v["rule_id"] for v in findings} == {"codex-hooks-valid"}
    assert {v["severity"] for v in findings} == {"error"}
    assert {v["message"] for v in findings} == {
        "Hooks file 'description' must be a string or null",
        "Unknown hooks file fields '$schema_note', '$note'; Codex refuses "
        "the file. Keep only 'description' and 'hooks' at the root",
    }
    assert {v["file_path"] for v in findings} == {
        "unknown/.codex/hooks.json",
        "description-list/.codex/hooks.json",
    }


def test_omitted_hook_collections_accept_defaults_and_empty_events_do_not_merge(tmp_path):
    repo = copy_fixture("codex/hooks-empty-defaults", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(CodexHooksBlock)
    assert len(blocks) == 4
    assert [
        handler.command
        for block in blocks
        for entries in block.events.values()
        for entry in entries
        for handler in entry.handlers
    ] == ["printf ready"]
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            "codex-hooks-valid",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["violations"] == []


def test_mcp_input_refuses_only_unrepresentable_values(tmp_path):
    repo = copy_fixture("codex/hooks-mcp-input", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(CodexHooksBlock)
    assert len(blocks) == 5
    result = run_cli(
        [
            "lint",
            str(repo),
            "--rule",
            "codex-hooks-valid",
            "--format",
            "json",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
        ]
    )
    assert result.returncode == 1, result.stdout + result.stderr
    findings = json.loads(result.stdout)["violations"]
    assert len(findings) == 3, findings
    assert {v["file_path"] for v in findings} == {
        "nested-null/.codex/hooks.json",
        "array-null/.codex/hooks.json",
        "unsigned-integers/.codex/hooks.json",
    }
    assert {v["rule_id"] for v in findings} == {"codex-hooks-valid"}
    assert {v["severity"] for v in findings} == {"error"}
    assert sum("'input' contains null" in v["message"] for v in findings) == 2
    assert (
        sum("unsigned integer outside TOML's signed 64-bit range" in v["message"] for v in findings)
        == 1
    )
