"""Integration tests for the LLM fix pipeline.

Each content rule is tested with both a FakeProvider (mocked, always runs) and
a real LLM (live, requires SKILLSAW_LLM_INTEGRATION=1 + OPENROUTER_API_KEY).
"""

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.llm._litellm import CompletionResult, ToolCall, TokenUsage
from skillsaw.rule import Severity

live = pytest.mark.skipif(
    not os.environ.get("SKILLSAW_LLM_INTEGRATION"),
    reason="Set SKILLSAW_LLM_INTEGRATION=1 to run live LLM tests",
)


class FakeProvider:
    """A CompletionProvider that returns scripted responses."""

    def __init__(self, responses: List[CompletionResult]):
        self._responses = list(responses)
        self._idx = 0

    def complete(self, messages, tools, model, max_tokens=4096):
        if self._idx >= len(self._responses):
            return CompletionResult(content="Done.", tool_calls=[], usage=TokenUsage(10, 10))
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


def _fake_fix_provider(fixed_content, path="CLAUDE.md"):
    """Build a FakeProvider that reads, writes fixed content, lints, and stops."""
    return FakeProvider(
        [
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="write_file",
                        arguments={"path": path, "content": fixed_content},
                    )
                ],
                usage=TokenUsage(100, 50),
            ),
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id="3", name="lint", arguments={"path": path})],
                usage=TokenUsage(100, 20),
            ),
            CompletionResult(
                content="Fixed.",
                tool_calls=[],
                usage=TokenUsage(100, 20),
            ),
        ]
    )


@dataclass
class FixCase:
    rule_id: str
    content: str
    fixed_content: str
    min_severity: Severity = Severity.WARNING
    extra_setup: Optional[Callable] = None
    extra_fixed_files: dict = field(default_factory=dict)


def _setup_editorconfig(tmp_path):
    (tmp_path / ".editorconfig").write_text("[*]\nindent_size = 2\n", encoding="utf-8")



def _setup_inconsistent_terminology(tmp_path):
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "deploy.md").write_text(
        "---\ndescription: deploy\n---\nCheck the folder structure before deploying.\n",
        encoding="utf-8",
    )


# Generate content for content-instruction-budget (needs 120+ instructions)
_budget_lines = "\n".join(f"Run check_{i} on every commit." for i in range(135))
_budget_content = f"# Instructions\n\n{_budget_lines}\n"
_budget_fixed_lines = "\n".join(f"Run check_{i} on every commit." for i in range(80))
_budget_fixed = f"# Instructions\n\n{_budget_fixed_lines}\n"

# Generate content for content-section-length (needs >500 tokens in one section)
_long_section_lines = "\n".join(
    f"Configure application setting number {i} to the recommended production value for optimal performance."
    for i in range(60)
)
_long_section_content = f"# Instructions\n\n{_long_section_lines}\n"
_long_section_fixed = (
    "# Instructions\n\n## Phase 1\n\n"
    + "\n".join(
        f"Configure application setting number {i} to the recommended production value for optimal performance."
        for i in range(30)
    )
    + "\n\n## Phase 2\n\n"
    + "\n".join(
        f"Configure application setting number {i} to the recommended production value for optimal performance."
        for i in range(30, 60)
    )
    + "\n"
)

# Generate content for content-cognitive-chunks (15+ lines, no headings)
_no_headings_lines = "\n".join(
    f"Configure setting_{i} to the recommended value." for i in range(16)
)
_no_headings_content = f"This file has no headings at all.\n\n{_no_headings_lines}\n"
_no_headings_fixed = (
    "# Configuration\n\nThis file has configuration settings.\n\n## Settings\n\n"
    + "\n".join(f"Configure setting_{i} to the recommended value." for i in range(16))
    + "\n"
)

# Content for content-critical-position (IMPORTANT buried in middle)
_critical_top = "\n".join(f"Normal instruction {i}." for i in range(20))
_critical_middle = "IMPORTANT: Never delete production data without a backup."
_critical_bottom = "\n".join(f"Normal instruction {i}." for i in range(20, 40))
_critical_content = f"# Instructions\n\n{_critical_top}\n{_critical_middle}\n{_critical_bottom}\n"
_critical_fixed = (
    f"# Instructions\n\nIMPORTANT: Never delete production data without a backup.\n\n"
    f"{_critical_top}\n{_critical_bottom}\n"
)

# Content for content-actionability-score (low verb density, vague prose)
_low_action_content = (
    "# Guidelines\n\n"
    "The system architecture is microservices-based.\n"
    "The frontend is a single-page application.\n"
    "The database schema has normalized tables.\n"
    "The deployment pipeline is containerized.\n"
    "The monitoring stack is Prometheus-based.\n"
    "The logging infrastructure is centralized.\n"
    "The authentication mechanism is token-based.\n"
    "The authorization model is role-based.\n"
    "The caching layer is Redis-backed.\n"
    "The message queue is RabbitMQ.\n"
)
_low_action_fixed = (
    "# Guidelines\n\n"
    "Use microservices architecture for all new services.\n"
    "Build the frontend as a single-page application with React.\n"
    "Use normalized tables in the database schema.\n"
    "Deploy using containers via `docker compose up`.\n"
    "Monitor with Prometheus at `http://prometheus:9090`.\n"
    "Send logs to the centralized logging service.\n"
    "Use JWT tokens for authentication.\n"
    "Implement role-based authorization checks.\n"
    "Cache frequently accessed data in Redis.\n"
    "Use RabbitMQ for async message processing.\n"
)


FIX_CASES = [
    FixCase(
        rule_id="content-weak-language",
        content="# Instructions\n\nTry to use consistent formatting.\nMaybe consider using TypeScript.\n",
        fixed_content="# Instructions\n\nUse consistent formatting.\nUse TypeScript.\n",
    ),
    FixCase(
        rule_id="content-tautological",
        content="# Rules\n\nWrite clean code.\nFollow best practices.\nBe thorough.\n",
        fixed_content="# Rules\n\n",
    ),
    FixCase(
        rule_id="content-critical-position",
        content=_critical_content,
        fixed_content=_critical_fixed,
        min_severity=Severity.INFO,
    ),
    FixCase(
        rule_id="content-redundant-with-tooling",
        content="# Rules\n\nUse 2 spaces for indentation.\nIndent with 4 spaces in Python.\n",
        fixed_content="# Rules\n\n",
        extra_setup=_setup_editorconfig,
    ),
    FixCase(
        rule_id="content-instruction-budget",
        content=_budget_content,
        fixed_content=_budget_fixed,
    ),
    FixCase(
        rule_id="content-negative-only",
        content=(
            "# Rules\n\n"
            "Don't use global variables in any module.\n"
            "Avoid using setTimeout for scheduling.\n"
        ),
        fixed_content=(
            "# Rules\n\n"
            "Use module-scoped variables instead of global variables.\n"
            "Use setInterval or a scheduler library instead of setTimeout.\n"
        ),
    ),
    FixCase(
        rule_id="content-section-length",
        content=_long_section_content,
        fixed_content=_long_section_fixed,
        min_severity=Severity.INFO,
    ),
    FixCase(
        rule_id="content-contradiction",
        content="# Rules\n\nMove fast and iterate quickly.\nWrite comprehensive tests for every change.\n",
        fixed_content="# Rules\n\nWrite focused tests for critical paths.\n",
    ),
    FixCase(
        rule_id="content-hook-candidate",
        content="# Rules\n\nAlways run tests before every commit.\nFormat code before committing.\n",
        fixed_content=(
            "# Rules\n\n"
            "Configure a pre-commit hook to run tests.\n"
            "Configure a pre-commit hook to format code.\n"
        ),
        min_severity=Severity.INFO,
    ),
    FixCase(
        rule_id="content-actionability-score",
        content=_low_action_content,
        fixed_content=_low_action_fixed,
        min_severity=Severity.INFO,
    ),
    FixCase(
        rule_id="content-cognitive-chunks",
        content=_no_headings_content,
        fixed_content=_no_headings_fixed,
        min_severity=Severity.INFO,
    ),
    FixCase(
        rule_id="content-embedded-secrets",
        content="# Config\n\nSet api_key = 'sk-abcdefghijklmnopqrstuvwxyz1234567890'\n",
        fixed_content="# Config\n\nSet api_key = $API_KEY from environment variables\n",
    ),
    FixCase(
        rule_id="content-banned-references",
        content="# Config\n\nUse claude-2 for summarization tasks.\nUse gpt-3.5 for classification.\n",
        fixed_content="# Config\n\nUse claude-sonnet-4 for summarization tasks.\nUse gpt-4o-mini for classification.\n",
    ),
    FixCase(
        rule_id="content-inconsistent-terminology",
        content="# Rules\n\nOrganize files into the correct directory structure.\n",
        fixed_content="# Rules\n\nOrganize files into the correct directory structure.\n",
        min_severity=Severity.INFO,
        extra_setup=_setup_inconsistent_terminology,
        extra_fixed_files={
            ".claude/commands/deploy.md": "---\ndescription: deploy\n---\nCheck the directory structure before deploying.\n"
        },
    ),
]


class TestLLMFixByRule:
    """Test that each LLM-fixable rule can be detected and fixed."""

    @pytest.mark.parametrize("case", FIX_CASES, ids=[c.rule_id for c in FIX_CASES])
    def test_mock_fix(self, tmp_path, case):
        _make_dot_claude_repo(tmp_path, case.content)
        if case.extra_setup:
            case.extra_setup(tmp_path)

        config = LinterConfig.default()
        config.llm.model = "fake-model"
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        rule_violations = [v for v in violations if v.rule_id == case.rule_id]
        assert len(rule_violations) >= 1, f"Expected violation for {case.rule_id}"

        provider = _fake_fix_provider(case.fixed_content)
        if case.extra_fixed_files:
            responses = list(provider._responses)
            for fpath, fcontent in case.extra_fixed_files.items():
                responses.insert(
                    -1,
                    CompletionResult(
                        content=None,
                        tool_calls=[
                            ToolCall(
                                id=f"extra-{fpath}",
                                name="write_file",
                                arguments={"path": fpath, "content": fcontent},
                            )
                        ],
                        usage=TokenUsage(100, 50),
                    ),
                )
            provider = FakeProvider(responses)

        result = linter.llm_fix(provider, min_severity=case.min_severity)
        assert result.violations_before > 0

    @pytest.mark.parametrize("case", FIX_CASES, ids=[c.rule_id for c in FIX_CASES])
    @live
    def test_live_fix(self, tmp_path, case):
        _make_dot_claude_repo(tmp_path, case.content)
        if case.extra_setup:
            case.extra_setup(tmp_path)

        config = LinterConfig.default()
        config.llm.model = os.environ.get("SKILLSAW_MODEL", "openrouter/minimax/minimax-m2.7")
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        rule_violations = [v for v in violations if v.rule_id == case.rule_id]
        assert len(rule_violations) >= 1, f"Expected violation for {case.rule_id}"

        from skillsaw.llm._litellm import LiteLLMProvider

        provider = LiteLLMProvider()
        result = linter.llm_fix(provider, min_severity=case.min_severity)
        assert result.violations_after < result.violations_before, (
            f"{case.rule_id}: expected improvement, got "
            f"{result.violations_before} → {result.violations_after}"
        )


class TestLLMFixPipelineRollback:
    """Test the per-file rollback behavior."""

    def test_rollback_on_no_improvement(self, tmp_path):
        content = "# Instructions\n\nTry to be careful when deploying.\n"
        _make_dot_claude_repo(tmp_path, content)

        config = LinterConfig.default()
        config.llm.model = "fake-model"
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        worse_content = "# Instructions\n\nTry to be careful when deploying.\nConsider using caution.\nIf possible, be careful.\n"
        rel_path = "CLAUDE.md"
        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": rel_path})],
                    usage=TokenUsage(100, 20),
                ),
                CompletionResult(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="write_file",
                            arguments={"path": rel_path, "content": worse_content},
                        )
                    ],
                    usage=TokenUsage(100, 50),
                ),
                CompletionResult(
                    content="Done.",
                    tool_calls=[],
                    usage=TokenUsage(100, 20),
                ),
            ]
        )

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
        config.llm.model = "fake-model"
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        fixed_content = "# Instructions\n\nUse consistent formatting.\n"
        rel_path = "CLAUDE.md"
        provider = _fake_fix_provider(fixed_content)

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
