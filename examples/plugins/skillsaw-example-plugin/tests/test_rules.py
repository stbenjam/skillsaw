"""Tests for the example plugin's rule.

Run with: pip install -e '.[dev]' skillsaw pytest && pytest
"""

import shutil
from pathlib import Path

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import invalidate_read_caches

from skillsaw_example_plugin import SKILLSAW_RULES
from skillsaw_example_plugin.rules import NoTodoInstructionsRule

FIXTURE = Path(__file__).parent / "fixture"


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def test_rule_is_exported():
    assert NoTodoInstructionsRule in SKILLSAW_RULES


def test_flags_todo_line(tmp_path):
    context = RepositoryContext(make_repo(tmp_path))
    violations = NoTodoInstructionsRule().check(context)
    assert len(violations) == 1
    assert violations[0].file_line == 9
    assert "TODO" in violations[0].message


def test_custom_patterns(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "CLAUDE.md").write_text(
        (repo / "CLAUDE.md").read_text(encoding="utf-8") + "\nHACK: temporary override.\n",
        encoding="utf-8",
    )
    context = RepositoryContext(repo)
    rule = NoTodoInstructionsRule({"patterns": ["HACK"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "HACK" in violations[0].message


def test_autofix_removes_only_flagged_lines(tmp_path):
    repo = make_repo(tmp_path)
    claude_md = repo / "CLAUDE.md"
    original_lines = claude_md.read_text(encoding="utf-8").splitlines()

    context = RepositoryContext(repo)
    rule = NoTodoInstructionsRule()
    violations = rule.check(context)
    fixes = rule.fix(context, violations)
    assert len(fixes) == 1
    claude_md.write_text(fixes[0].fixed_content, encoding="utf-8")

    fixed_lines = claude_md.read_text(encoding="utf-8").splitlines()
    assert fixed_lines == [ln for ln in original_lines if "TODO" not in ln]

    # Idempotent: re-checking the fixed content finds nothing. skillsaw
    # caches file reads, so tests that rewrite files in-process must
    # invalidate before re-checking (the CLI does this automatically).
    invalidate_read_caches()
    context = RepositoryContext(repo)
    assert rule.check(context) == []
