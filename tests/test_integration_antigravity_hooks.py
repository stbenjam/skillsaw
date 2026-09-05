"""Fixture CLI coverage of Antigravity hook decoding and shared policy visibility."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import AntigravityHooksBlock
from skillsaw.context import RepositoryContext
from tests.antigravity._helpers import copy_fixture
from tests.cli_runner import run_cli

RULE = "antigravity-hooks-valid"
FILE = ".agents/hooks.json"


def _fixture(tmp_path, name):
    repo = copy_fixture(f"antigravity/hooks-decoder/{name}", tmp_path)
    blocks = RepositoryContext(repo).lint_tree.find(AntigravityHooksBlock)
    assert [str(b.path.relative_to(repo)) for b in blocks] == [FILE]
    return repo, blocks[0]


def _lint(repo, *options):
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
            *options,
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode, json.loads(result.stdout)["violations"]


def _commands(events):
    return [
        h.command
        for configs in events.values()
        for cfg in configs
        for h in cfg.handlers
        if h.command
    ]


def test_valid_case_aliases_reach_handlers_and_docs(tmp_path):
    repo, block = _fixture(tmp_path, "accepted")
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    prompt = block.events["Stop"][0].handlers[0]
    assert (prompt.type, prompt.prompt, prompt.model, prompt.timeout) == (
        "prompt",
        "Check formatting.",
        "example-model",
        5,
    )
    assert _commands(block.events) == ["/audit/not-an-executable"]
    assert block.events["PreToolUse"][0].matcher == "read_file"
    assert "PreToolUse" not in block.effective_events


def test_null_strings_preserve_command_and_prompt_type(tmp_path):
    repo, block = _fixture(tmp_path, "null-strings")
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    assert [cfg.handlers[0].type for cfg in block.events["Stop"]] == ["prompt", "command"]
    assert _commands(block.events) == ["/audit/retained-command"]


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_wrong_types_use_primary_configured_severity(tmp_path, severity):
    repo, _ = _fixture(tmp_path, "dropped")
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    severity: {severity}\n")
    code, findings = _lint(repo)
    assert code == (1 if severity == "error" else 0)
    assert len(findings) == 4
    assert {(v["rule_id"], v["file_path"], v["severity"]) for v in findings} == {
        (RULE, FILE, severity)
    }
    for name in ("command-review", "timeout-review", "enabled-review", "type-review"):
        assert sum(f"hook '{name}'" in v["message"] for v in findings) == 1


def test_replacement_keeps_errors_but_only_effective_commands(tmp_path):
    repo, block = _fixture(tmp_path, "replaced-invalid")
    code, findings = _lint(repo, "--rule", RULE)
    assert code == 1
    assert len(findings) == 1
    assert "'Command' must be a string" in findings[0]["message"]
    assert _commands(block.events) == ["/audit/not-an-executable"]


def test_valid_replacements_and_cleared_arrays_keep_only_final_commands(tmp_path):
    repo, block = _fixture(tmp_path, "replaced-valid")
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    assert _commands(block.events) == ["/audit/final"]
    assert _commands(block.effective_events) == ["/audit/final"]


def test_null_root_is_an_explicit_empty_config(tmp_path):
    repo, block = _fixture(tmp_path, "null-root")
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    assert block.events == {}


def test_ignored_finite_overflow_is_only_an_unknown_key_advisory(tmp_path):
    repo, _ = _fixture(tmp_path, "overflow")
    code, findings = _lint(repo, "--rule", RULE)
    assert code == 0
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert "unknown handler key 'metadata' is ignored" in findings[0]["message"]


def test_disabling_shape_lint_keeps_disabled_and_nested_commands_visible(tmp_path):
    repo, block = _fixture(tmp_path, "policy")
    (repo / ".skillsaw.yaml").write_text(
        f"rules:\n  {RULE}:\n    enabled: false\n  hooks-prohibited:\n    enabled: true\n"
    )
    code, findings = _lint(repo)
    assert code == 1
    assert len(findings) == 2
    assert {(v["rule_id"], v["file_path"]) for v in findings} == {("hooks-prohibited", FILE)}
    for command in ("/audit/flat", "/audit/nested"):
        assert sum(command in v["message"] for v in findings) == 1
    assert set(_commands(block.events)) == {"/audit/flat", "/audit/nested"}
    assert block.effective_events == {}
