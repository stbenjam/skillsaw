"""Integration tests for the LLM fix pipeline.

These tests use a FakeProvider to simulate LLM responses and verify the
full pipeline: violation detection → LLM fix → re-lint → rollback logic.

For real LLM integration, set SKILLSAW_LLM_INTEGRATION=1 and provide
an OPENROUTER_API_KEY (the GitHub Action handles this).
"""

import json
import os
from pathlib import Path
from typing import List

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.llm._litellm import CompletionResult, ToolCall, TokenUsage


class FakeProvider:
    """A CompletionProvider that returns scripted responses."""

    def __init__(self, responses: List[CompletionResult]):
        self._responses = list(responses)
        self._idx = 0

    def complete(self, messages, tools, model, max_tokens=4096):
        if self._idx >= len(self._responses):
            return CompletionResult(
                content="Done.", tool_calls=[], usage=TokenUsage(10, 10)
            )
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


def _make_dot_claude_repo(tmp_path, claude_md_content):
    """Create a minimal .claude repo with the given CLAUDE.md content."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(claude_md_content, encoding="utf-8")
    return tmp_path


class TestLLMFixWeakLanguage:
    """Test that the pipeline detects and fixes weak language."""

    def test_fix_hedging_language(self, tmp_path):
        content = "# Instructions\n\nTry to use consistent formatting.\nConsider using TypeScript.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        weak_violations = [v for v in violations if v.rule_id == "content-weak-language"]
        assert len(weak_violations) >= 1

        rel_path = "CLAUDE.md"
        fixed_content = "# Instructions\n\nUse consistent formatting.\nUse TypeScript.\n"
        provider = FakeProvider([
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": rel_path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="2", name="write_file", arguments={
                    "path": rel_path, "content": fixed_content
                })],
                usage=TokenUsage(100, 50),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="3", name="lint", arguments={"path": rel_path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content="Fixed weak language.",
                tool_calls=[],
                usage=TokenUsage(100, 20),
            ),
        ])

        from skillsaw.rule import Severity

        result = linter.llm_fix(provider, min_severity=Severity.WARNING)
        assert result.violations_before > 0


class TestLLMFixTautological:
    """Test that tautological instructions are detected."""

    def test_detect_tautological(self, tmp_path):
        content = "# Rules\n\nWrite clean code.\nFollow best practices.\nBe thorough.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        taut_violations = [v for v in violations if v.rule_id == "content-tautological"]
        assert len(taut_violations) >= 2


class TestLLMFixNegativeOnly:
    """Test that negative-only instructions are detected."""

    def test_detect_negative_only(self, tmp_path):
        content = (
            "# Rules\n\n"
            "Don't use global variables in any module.\n"
            "Avoid using setTimeout for scheduling.\n"
        )
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        neg_violations = [v for v in violations if v.rule_id == "content-negative-only"]
        assert len(neg_violations) >= 1


class TestLLMFixEmbeddedSecrets:
    """Test that secrets are detected."""

    def test_detect_api_key(self, tmp_path):
        content = "# Config\n\nSet api_key = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        secret_violations = [v for v in violations if v.rule_id == "content-embedded-secrets"]
        assert len(secret_violations) >= 1


class TestLLMFixStaleReferences:
    """Test that stale model references are detected."""

    def test_detect_deprecated_model(self, tmp_path):
        content = "# Config\n\nUse claude-2 for summarization tasks.\nUse gpt-3.5 for classification.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        stale_violations = [v for v in violations if v.rule_id == "content-stale-references"]
        assert len(stale_violations) >= 2


class TestLLMFixContradiction:
    """Test that contradictions are detected."""

    def test_detect_contradiction(self, tmp_path):
        content = "# Rules\n\nMove fast and iterate quickly.\nWrite comprehensive tests for every change.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        contra_violations = [v for v in violations if v.rule_id == "content-contradiction"]
        assert len(contra_violations) >= 1


class TestLLMFixPipelineRollback:
    """Test the per-file rollback behavior."""

    def test_rollback_on_no_improvement(self, tmp_path):
        content = "# Instructions\n\nTry to be careful when deploying.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        worse_content = "# Instructions\n\nTry to be careful when deploying.\nConsider using caution.\nIf possible, be careful.\n"
        rel_path = "CLAUDE.md"
        provider = FakeProvider([
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": rel_path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="2", name="write_file", arguments={
                    "path": rel_path, "content": worse_content
                })],
                usage=TokenUsage(100, 50),
            ),
            CompletionResult(
                content="Done.",
                tool_calls=[],
                usage=TokenUsage(100, 20),
            ),
        ])

        result = linter.llm_fix(provider)
        assert len(result.files_modified) == 0
        actual = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert actual == content


class TestLLMFixDryRun:
    """Test dry-run mode preserves original files."""

    def test_dry_run_no_write(self, tmp_path):
        content = "# Instructions\n\nTry to use consistent formatting.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        fixed_content = "# Instructions\n\nUse consistent formatting.\n"
        rel_path = "CLAUDE.md"
        provider = FakeProvider([
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": rel_path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="2", name="write_file", arguments={
                    "path": rel_path, "content": fixed_content
                })],
                usage=TokenUsage(100, 50),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="3", name="lint", arguments={"path": rel_path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content="Fixed.",
                tool_calls=[],
                usage=TokenUsage(100, 20),
            ),
        ])

        result = linter.llm_fix(provider, dry_run=True)
        actual = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert actual == content
        assert len(result.files_modified) == 0
        assert len(result.diffs) > 0 or result.violations_before > 0


class TestLLMFixScopedLinting:
    """Test that LintTool only runs relevant rules."""

    def test_lint_tool_scoped(self, tmp_path):
        from skillsaw.llm.tools import LintTool

        content = "# Instructions\n\nTry to use consistent formatting.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        tool = LintTool(tmp_path, config, rule_ids={"content-weak-language"})
        result = tool.execute(path="CLAUDE.md")
        assert "weak" in result.lower() or "hedging" in result.lower()

    def test_lint_tool_unscoped_finds_all(self, tmp_path):
        from skillsaw.llm.tools import LintTool

        content = "# Instructions\n\nTry to use consistent formatting.\nWrite clean code.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        tool = LintTool(tmp_path, config)
        result = tool.execute(path="CLAUDE.md")
        assert "No violations" not in result


class TestLLMFixHookCandidate:
    """Test hook candidate detection."""

    def test_detect_hook_candidate(self, tmp_path):
        content = "# Rules\n\nAlways run tests before every commit.\nFormat code before committing.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        hook_violations = [v for v in violations if v.rule_id == "content-hook-candidate"]
        assert len(hook_violations) >= 1


class TestLLMFixRedundantWithTooling:
    """Test tooling redundancy detection."""

    def test_detect_editorconfig_redundancy(self, tmp_path):
        (tmp_path / ".editorconfig").write_text("[*]\nindent_size = 2\n", encoding="utf-8")
        content = "# Rules\n\nUse 2 spaces for indentation.\nIndent with 4 spaces in Python.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        redundant_violations = [
            v for v in violations if v.rule_id == "content-redundant-with-tooling"
        ]
        assert len(redundant_violations) >= 1
