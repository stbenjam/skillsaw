"""
Tests for deep Claude Code rules
"""

import json
import pytest
from pathlib import Path

from skillsaw.rules.builtin.claude_deep import (
    ClaudeMdQualityRule,
    ClaudeMdHookMigrationRule,
    ClaudeSkillQualityRule,
    ClaudeMcpSecurityRule,
    ClaudePluginSizeRule,
    ClaudeRulesOverlapRule,
    ClaudeAgentDelegationRule,
    ClaudeContextBudgetRule,
)
from skillsaw.rule import Severity
from skillsaw.context import RepositoryContext


def _make_dot_claude(temp_dir):
    """Create a minimal .claude/ structure so repo is detected as DOT_CLAUDE."""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "commands").mkdir(exist_ok=True)
    return claude_dir


# ── claude-md-quality ────────────────────────────────────────────────────


class TestClaudeMdQualityRule:
    def test_clean_file_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text(
            "# Project Instructions\n\nUse pytest for all tests. Run `make lint` before committing.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdQualityRule().check(ctx)
        assert len(violations) == 0

    def test_weak_language_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        lines = [
            "# Instructions",
            "Try to use pytest.",
            "Maybe run lint.",
            "If possible, format code.",
            "Consider using type hints.",
            "Ideally write docs.",
            "You might want to test.",
        ]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdQualityRule().check(ctx)
        assert any("weak" in v.message.lower() for v in violations)

    def test_tautology_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nYou are an AI assistant. Be helpful and follow the instructions.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdQualityRule().check(ctx)
        tautology_violations = [v for v in violations if "tautolog" in v.message.lower()]
        assert len(tautology_violations) >= 1

    def test_short_body_warning(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("---\ntitle: test\n---\nHi.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdQualityRule().check(ctx)
        assert any("body" in v.message.lower() and "characters" in v.message for v in violations)

    def test_no_claude_md_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdQualityRule().check(ctx)
        assert len(violations) == 0


# ── claude-md-hook-migration ─────────────────────────────────────────────


class TestClaudeMdHookMigrationRule:
    def test_lint_after_instruction_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nAlways run linter after saving files.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdHookMigrationRule().check(ctx)
        assert len(violations) >= 1
        assert "PostToolUse" in violations[0].message

    def test_never_push_to_main_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("# Rules\n\nNever push to main directly.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdHookMigrationRule().check(ctx)
        assert len(violations) >= 1
        assert "Stop" in violations[0].message

    def test_format_before_commit_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("# Rules\n\nFormat before committing code.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdHookMigrationRule().check(ctx)
        assert len(violations) >= 1

    def test_clean_file_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("# Project\n\nUse Python 3.12. Follow PEP 8.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMdHookMigrationRule().check(ctx)
        assert len(violations) == 0


# ── claude-skill-quality ─────────────────────────────────────────────────


class TestClaudeSkillQualityRule:
    def test_good_skill_no_violations(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "deploy"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: Deploy the application\n---\n\n"
            "This skill handles deployment to production environments.\n\n"
            "## Usage\n\nRun /deploy to start.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeSkillQualityRule().check(ctx)
        assert len(violations) == 0

    def test_oversized_skill_warned(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "huge"
        skill_dir.mkdir()
        lines = ["---\nname: huge\ndescription: Too big\n---\n"]
        lines.extend(["This is line content for testing.\n"] * 250)
        (skill_dir / "SKILL.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeSkillQualityRule().check(ctx)
        assert any("lines" in v.message for v in violations)

    def test_no_purpose_warned(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "empty"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: empty\ndescription: x\n---\n\n# Title\n\nHi\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeSkillQualityRule().check(ctx)
        assert any("purpose" in v.message.lower() for v in violations)


# ── claude-mcp-security ──────────────────────────────────────────────────


class TestClaudeMcpSecurityRule:
    def test_risky_command_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        mcp_data = {
            "mcpServers": {
                "shell": {"type": "stdio", "command": "bash"},
            }
        }
        (temp_dir / ".mcp.json").write_text(json.dumps(mcp_data))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMcpSecurityRule().check(ctx)
        assert any("unrestricted" in v.message.lower() for v in violations)

    def test_http_without_tls_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        mcp_data = {
            "mcpServers": {
                "remote": {"type": "sse", "url": "http://api.example.com/sse"},
            }
        }
        (temp_dir / ".mcp.json").write_text(json.dumps(mcp_data))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMcpSecurityRule().check(ctx)
        assert any("http" in v.message.lower() for v in violations)

    def test_localhost_http_ok(self, temp_dir):
        _make_dot_claude(temp_dir)
        mcp_data = {
            "mcpServers": {
                "local": {"type": "sse", "url": "http://localhost:8080/sse"},
            }
        }
        (temp_dir / ".mcp.json").write_text(json.dumps(mcp_data))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMcpSecurityRule().check(ctx)
        assert len(violations) == 0

    def test_missing_env_vars_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        mcp_data = {
            "mcpServers": {
                "api": {
                    "type": "stdio",
                    "command": "/usr/bin/my-tool",
                    "args": ["--key", "${MY_API_KEY}"],
                },
            }
        }
        (temp_dir / ".mcp.json").write_text(json.dumps(mcp_data))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMcpSecurityRule().check(ctx)
        assert any("MY_API_KEY" in v.message for v in violations)

    def test_safe_config_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        mcp_data = {
            "mcpServers": {
                "tool": {
                    "type": "stdio",
                    "command": "/usr/local/bin/my-mcp-server",
                    "args": ["--config", "prod.json"],
                },
            }
        }
        (temp_dir / ".mcp.json").write_text(json.dumps(mcp_data))
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeMcpSecurityRule().check(ctx)
        assert len(violations) == 0


# ── claude-plugin-size ───────────────────────────────────────────────────


class TestClaudePluginSizeRule:
    def test_small_plugin_no_violations(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (claude_dir / "commands").mkdir(exist_ok=True)
        (claude_dir / "commands" / "small.md").write_text(
            "---\ndescription: small\n---\n# Small\nDo something.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudePluginSizeRule().check(ctx)
        assert len(violations) == 0

    def test_large_plugin_warned(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (claude_dir / "commands").mkdir(exist_ok=True)
        big = "x" * 40000
        (claude_dir / "commands" / "big.md").write_text(big)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudePluginSizeRule().check(ctx)
        assert len(violations) >= 1

    def test_very_large_plugin_errors(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (claude_dir / "commands").mkdir(exist_ok=True)
        big = "x" * 80000
        (claude_dir / "commands" / "huge.md").write_text(big)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudePluginSizeRule().check(ctx)
        assert any(v.severity == Severity.ERROR for v in violations)


# ── claude-rules-overlap ─────────────────────────────────────────────────


class TestClaudeRulesOverlapRule:
    def test_overlapping_globs_detected(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "python.md").write_text('---\npaths:\n  - "**/*.py"\n---\n# Python rules\n')
        (rules_dir / "tests.md").write_text('---\npaths:\n  - "**/*.py"\n---\n# Test rules\n')
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeRulesOverlapRule().check(ctx)
        assert len(violations) >= 1
        assert "overlap" in violations[0].message.lower()

    def test_disjoint_globs_no_violations(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "python.md").write_text(
            '---\npaths:\n  - "src/**/*.py"\n---\n# Python rules\n'
        )
        (rules_dir / "js.md").write_text('---\npaths:\n  - "frontend/**/*.js"\n---\n# JS rules\n')
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeRulesOverlapRule().check(ctx)
        assert len(violations) == 0

    def test_no_frontmatter_no_violations(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "general.md").write_text("# General rules\nBe consistent.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeRulesOverlapRule().check(ctx)
        assert len(violations) == 0


# ── claude-agent-delegation ──────────────────────────────────────────────


class TestClaudeAgentDelegationRule:
    def test_vague_agent_detected(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "AGENTS.md").write_text("# Agents\n\n## Helper\n\nDoes stuff.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeAgentDelegationRule().check(ctx)
        assert any("vague" in v.message.lower() for v in violations)

    def test_good_agent_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "AGENTS.md").write_text(
            "# Agents\n\n## Code Reviewer\n\n"
            "Reviews pull requests for code quality, security issues, and style compliance. "
            "Has read-only tool access to the repository. Restricted scope to review tasks only.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeAgentDelegationRule().check(ctx)
        vague = [v for v in violations if "vague" in v.message.lower()]
        assert len(vague) == 0

    def test_missing_tool_access_info(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "AGENTS.md").write_text(
            "# Agents\n\n## Deployer\n\n"
            "Handles deployment to production environments including staging and rollbacks.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeAgentDelegationRule().check(ctx)
        info_violations = [v for v in violations if v.severity == Severity.INFO]
        assert any("tool" in v.message.lower() for v in info_violations)

    def test_no_agents_md_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeAgentDelegationRule().check(ctx)
        assert len(violations) == 0


# ── claude-context-budget-total ──────────────────────────────────────────


class TestClaudeContextBudgetRule:
    def test_small_budget_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\nUse pytest.\n")
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeContextBudgetRule().check(ctx)
        assert len(violations) == 0

    def test_large_budget_warns(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("x" * 20000)
        rules_dir = claude_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "big.md").write_text("y" * 20000)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeContextBudgetRule().check(ctx)
        assert len(violations) >= 1
        assert "breakdown" in violations[0].message.lower()

    def test_breakdown_includes_categories(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("x" * 20000)
        skills_dir = claude_dir / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("z" * 20000)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeContextBudgetRule().check(ctx)
        assert len(violations) >= 1
        msg = violations[0].message
        assert "CLAUDE.md" in msg
        assert ".claude/skills" in msg

    def test_very_large_budget_errors(self, temp_dir):
        claude_dir = _make_dot_claude(temp_dir)
        (temp_dir / "CLAUDE.md").write_text("x" * 70000)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeContextBudgetRule().check(ctx)
        assert any(v.severity == Severity.ERROR for v in violations)

    def test_no_context_files_no_violations(self, temp_dir):
        _make_dot_claude(temp_dir)
        ctx = RepositoryContext(temp_dir)
        violations = ClaudeContextBudgetRule().check(ctx)
        assert len(violations) == 0
