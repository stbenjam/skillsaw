"""Tests for context budget / token counting rule"""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig
from skillsaw.rule import Severity
from skillsaw.rules.builtin.context_budget import (
    ContextBudgetRule,
    _estimate_tokens,
    _parse_limit,
    DEFAULT_LIMITS,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


def _make_text(token_target: int) -> str:
    """Generate text that estimates to approximately token_target tokens."""
    return "x" * (token_target * 4)


class TestParseLimit:
    def test_int_is_warn_only(self):
        assert _parse_limit(2000) == (2000, None)

    def test_dict_with_both(self):
        assert _parse_limit({"warn": 3000, "error": 6000}) == (3000, 6000)

    def test_dict_warn_only(self):
        assert _parse_limit({"warn": 3000}) == (3000, None)

    def test_dict_error_only(self):
        assert _parse_limit({"error": 6000}) == (None, 6000)

    def test_none_returns_none(self):
        assert _parse_limit(None) == (None, None)

    def test_string_returns_none(self):
        assert _parse_limit("invalid") == (None, None)


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 0

    def test_four_chars_is_one_token(self):
        assert _estimate_tokens("abcd") == 1

    def test_known_length(self):
        assert _estimate_tokens("x" * 4000) == 1000


class TestContextBudgetRule:
    def test_rule_metadata(self):
        rule = ContextBudgetRule()
        assert rule.rule_id == "context-budget"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None
        assert "limits" in rule.config_schema

    def test_disabled_by_default(self):
        config = LinterConfig.default()
        rule_config = config.get_rule_config("context-budget")
        assert rule_config["enabled"] is False

    def test_under_limit_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Short\nHello.\n")
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_over_warn_limit_warns(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(_make_text(7000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "warn" in violations[0].message.lower()

    def test_over_error_limit_errors(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(_make_text(13000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert "error" in violations[0].message.lower()

    def test_custom_warn_limit(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(_make_text(150))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule({"limits": {"claude-md": 100}})
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING

    def test_custom_warn_and_error_limits(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(_make_text(500))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule({"limits": {"claude-md": {"warn": 100, "error": 400}}})
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR

    def test_agents_md_checked(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(_make_text(7000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1

    def test_gemini_md_checked(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text(_make_text(7000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1

    def test_skill_files_checked(self, temp_dir):
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(_make_text(4000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "skill" in violations[0].message

    def test_command_files_checked(self, temp_dir):
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        commands_dir = claude_dir / "commands"
        commands_dir.mkdir()
        (commands_dir / "big-cmd.md").write_text("---\ndescription: test\n---\n" + _make_text(3000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "command" in violations[0].message

    def test_agent_files_checked(self, temp_dir):
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        agents_dir = claude_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "big-agent.md").write_text(
            "---\nname: big\ndescription: test\n---\n" + _make_text(3000)
        )
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "agent" in violations[0].message

    def test_rule_files_checked(self, temp_dir):
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "big-rule.md").write_text(_make_text(3000))
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "rule" in violations[0].message

    def test_missing_files_no_error(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = ContextBudgetRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_token_estimation_boundary(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("x" * 4000)
        context = RepositoryContext(temp_dir)
        rule_at = ContextBudgetRule({"limits": {"claude-md": 1000}})
        assert len(rule_at.check(context)) == 0

        rule_under = ContextBudgetRule({"limits": {"claude-md": 999}})
        assert len(rule_under.check(context)) == 1
