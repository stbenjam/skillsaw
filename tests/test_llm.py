"""Tests for the LLM-as-judge autofix engine."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest

from skillsaw.llm._litellm import CompletionResult, ToolCall, TokenUsage
from skillsaw.llm.engine import LLMEngine, LLMResult, ToolCallRecord
from skillsaw.llm.tools import (
    ReadFileTool,
    WriteFileTool,
    ReplaceSectionTool,
    DiffTool,
    LintTool,
    BlockState,
    ReadBlockTool,
    WriteBlockTool,
    ReplaceBlockSectionTool,
    DiffBlockTool,
    LintBlockTool,
)
from skillsaw.rules.builtin.content_analysis import FileContentBlock as ContentBlock
from skillsaw.rule import AutofixConfidence, Severity


class FakeProvider:
    """A CompletionProvider that returns scripted responses."""

    def __init__(self, responses: List[CompletionResult]):
        self._responses = iter(responses)

    def complete(self, messages, tools, model, max_tokens=4096):
        return next(self._responses)


class TestAutoFixConfidence:
    def test_llm_value_exists(self):
        assert AutofixConfidence.LLM.value == "llm"

    def test_all_values(self):
        values = {e.value for e in AutofixConfidence}
        assert values == {"safe", "suggest", "llm"}


class TestReadFileTool:
    def test_read_existing(self, tmp_path):
        (tmp_path / "test.md").write_text("hello world", encoding="utf-8")
        tool = ReadFileTool(tmp_path)
        assert tool.execute(path="test.md") == "hello world"

    def test_read_missing(self, tmp_path):
        tool = ReadFileTool(tmp_path)
        result = tool.execute(path="missing.md")
        assert "Error: file not found" in result

    def test_path_traversal(self, tmp_path):
        tool = ReadFileTool(tmp_path)
        result = tool.execute(path="../../../etc/passwd")
        assert "Error: path escapes repository root" in result

    def test_read_directory(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        tool = ReadFileTool(tmp_path)
        result = tool.execute(path="subdir")
        assert "Error: path is a directory" in result

    def test_read_binary_file(self, tmp_path):
        (tmp_path / "binary.bin").write_bytes(b"\x80\x81\x82\xff\xfe")
        tool = ReadFileTool(tmp_path)
        result = tool.execute(path="binary.bin")
        assert "Error: file is not valid UTF-8 text" in result

    def test_tool_metadata(self):
        tool = ReadFileTool(Path("/tmp"))
        assert tool.name == "read_file"
        assert tool.description
        assert "path" in tool.parameters["properties"]


class TestWriteFileTool:
    def test_write_new(self, tmp_path):
        tool = WriteFileTool(tmp_path)
        result = tool.execute(path="new.md", content="new content")
        assert "Wrote" in result
        assert (tmp_path / "new.md").read_text() == "new content"

    def test_write_overwrite(self, tmp_path):
        (tmp_path / "existing.md").write_text("old", encoding="utf-8")
        tool = WriteFileTool(tmp_path)
        tool.execute(path="existing.md", content="new")
        assert (tmp_path / "existing.md").read_text() == "new"

    def test_path_traversal(self, tmp_path):
        tool = WriteFileTool(tmp_path)
        result = tool.execute(path="../escape.md", content="bad")
        assert "Error: path escapes repository root" in result

    def test_creates_parent_dirs(self, tmp_path):
        tool = WriteFileTool(tmp_path)
        tool.execute(path="sub/dir/file.md", content="nested")
        assert (tmp_path / "sub" / "dir" / "file.md").read_text() == "nested"

    def test_write_to_existing_directory(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        tool = WriteFileTool(tmp_path)
        result = tool.execute(path="subdir", content="data")
        assert "Error: path is an existing directory" in result

    def test_write_parent_is_file(self, tmp_path):
        (tmp_path / "afile").write_text("I am a file", encoding="utf-8")
        tool = WriteFileTool(tmp_path)
        result = tool.execute(path="afile/child.md", content="data")
        assert "Error: a parent component of the path is a file" in result


class TestReplaceSectionTool:
    def test_replace_unique(self, tmp_path):
        (tmp_path / "test.md").write_text("Hello world", encoding="utf-8")
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="test.md", old_text="Hello", new_text="Goodbye")
        assert "Replaced 1 occurrence" in result
        assert (tmp_path / "test.md").read_text() == "Goodbye world"

    def test_replace_not_found(self, tmp_path):
        (tmp_path / "test.md").write_text("Hello world", encoding="utf-8")
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="test.md", old_text="missing", new_text="x")
        assert "Error: old_text not found" in result

    def test_replace_multiple_matches(self, tmp_path):
        (tmp_path / "test.md").write_text("aaa bbb aaa", encoding="utf-8")
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="test.md", old_text="aaa", new_text="ccc")
        assert "found 2 times" in result

    def test_path_traversal(self, tmp_path):
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="../escape.md", old_text="a", new_text="b")
        assert "Error: path escapes repository root" in result

    def test_file_missing(self, tmp_path):
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="missing.md", old_text="a", new_text="b")
        assert "Error: file not found" in result

    def test_replace_on_directory(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="subdir", old_text="a", new_text="b")
        assert "Error: path is a directory" in result

    def test_replace_on_binary_file(self, tmp_path):
        (tmp_path / "binary.bin").write_bytes(b"\x80\x81\x82\xff\xfe")
        tool = ReplaceSectionTool(tmp_path)
        result = tool.execute(path="binary.bin", old_text="a", new_text="b")
        assert "Error: file is not valid UTF-8 text" in result


class TestDiffTool:
    def test_diff_with_changes(self, tmp_path):
        original = "line 1\nline 2\nline 3\n"
        (tmp_path / "test.md").write_text("line 1\nmodified\nline 3\n", encoding="utf-8")
        tool = DiffTool(tmp_path, {(tmp_path / "test.md").resolve(): original})
        result = tool.execute(path="test.md")
        assert "-line 2" in result
        assert "+modified" in result

    def test_diff_no_changes(self, tmp_path):
        content = "unchanged\n"
        resolved = (tmp_path / "test.md").resolve()
        (tmp_path / "test.md").write_text(content, encoding="utf-8")
        tool = DiffTool(tmp_path, {resolved: content})
        result = tool.execute(path="test.md")
        assert result == "No changes."

    def test_diff_new_file(self, tmp_path):
        content = "new content\n"
        (tmp_path / "test.md").write_text(content, encoding="utf-8")
        resolved = (tmp_path / "test.md").resolve()
        tool = DiffTool(tmp_path, {resolved: None})
        result = tool.execute(path="test.md")
        assert "+new content" in result

    def test_diff_no_snapshot(self, tmp_path):
        (tmp_path / "test.md").write_text("content", encoding="utf-8")
        tool = DiffTool(tmp_path, {})
        result = tool.execute(path="test.md")
        assert "Error: no original snapshot" in result

    def test_path_traversal(self, tmp_path):
        tool = DiffTool(tmp_path, {})
        result = tool.execute(path="../escape.md")
        assert "Error: path escapes repository root" in result


class TestLLMEngine:
    def test_simple_text_response(self):
        provider = FakeProvider(
            [
                CompletionResult(
                    content="Done fixing!",
                    tool_calls=[],
                    usage=TokenUsage(100, 50),
                )
            ]
        )
        engine = LLMEngine(provider, [])
        result = engine.run("system prompt", "user message")
        assert result.text == "Done fixing!"
        assert result.iterations == 1
        assert not result.budget_exhausted
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 50

    def test_tool_call_then_text(self, tmp_path):
        (tmp_path / "test.md").write_text("hello", encoding="utf-8")
        tool = ReadFileTool(tmp_path)

        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[
                        ToolCall(id="call_1", name="read_file", arguments={"path": "test.md"})
                    ],
                    usage=TokenUsage(100, 20),
                ),
                CompletionResult(
                    content="File contains: hello",
                    tool_calls=[],
                    usage=TokenUsage(150, 30),
                ),
            ]
        )

        engine = LLMEngine(provider, [tool])
        result = engine.run("system", "read test.md")
        assert result.text == "File contains: hello"
        assert result.iterations == 2
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].result == "hello"
        assert result.usage.prompt_tokens == 250
        assert result.usage.completion_tokens == 50

    def test_budget_exhaustion(self):
        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="unknown", arguments={})],
                    usage=TokenUsage(80, 30),
                ),
            ]
        )
        engine = LLMEngine(provider, [], max_tokens=100)
        result = engine.run("system", "user")
        assert result.iterations == 2
        assert result.budget_exhausted

    def test_max_iterations(self):
        responses = [
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id=f"call_{i}", name="unknown", arguments={})],
                usage=TokenUsage(10, 10),
            )
            for i in range(5)
        ]
        provider = FakeProvider(responses)
        engine = LLMEngine(provider, [], max_iterations=2)
        result = engine.run("system", "user")
        assert result.iterations == 2

    def test_unknown_tool(self):
        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="unknown_tool", arguments={})],
                    usage=TokenUsage(10, 10),
                ),
                CompletionResult(
                    content="ok",
                    tool_calls=[],
                    usage=TokenUsage(10, 10),
                ),
            ]
        )
        engine = LLMEngine(provider, [])
        result = engine.run("system", "user")
        assert len(result.tool_calls) == 1
        assert "Error: unknown tool" in result.tool_calls[0].result

    def test_none_usage_in_result(self):
        """Engine should not crash when CompletionResult.usage is None."""
        provider = FakeProvider(
            [
                CompletionResult(
                    content="Done!",
                    tool_calls=[],
                    usage=None,
                )
            ]
        )
        engine = LLMEngine(provider, [])
        result = engine.run("system", "user")
        assert result.text == "Done!"
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0

    def test_none_usage_with_tool_calls(self):
        """Engine should not crash when usage is None across multiple iterations."""
        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="unknown", arguments={})],
                    usage=None,
                ),
                CompletionResult(
                    content="ok",
                    tool_calls=[],
                    usage=TokenUsage(10, 10),
                ),
            ]
        )
        engine = LLMEngine(provider, [])
        result = engine.run("system", "user")
        assert result.text == "ok"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 10


class TestLiteLLMProviderEdgeCases:
    """Tests for edge cases in the LiteLLM provider's complete() method."""

    def test_empty_choices_list(self):
        """Provider should return empty result but still extract usage when choices is empty."""
        from unittest.mock import MagicMock, patch
        from skillsaw.llm._litellm import LiteLLMProvider

        mock_litellm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = []
        mock_response.usage.prompt_tokens = 42
        mock_response.usage.completion_tokens = 0
        mock_litellm.completion.return_value = mock_response

        provider = LiteLLMProvider()
        with patch("skillsaw.llm._litellm._get_litellm", return_value=mock_litellm):
            result = provider.complete(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                model="test-model",
            )

        assert result.content is None
        assert result.tool_calls == []
        assert result.usage.prompt_tokens == 42
        assert result.usage.completion_tokens == 0

    def test_missing_choices_attribute(self):
        """Provider should return empty result when response has no choices attribute."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from skillsaw.llm._litellm import LiteLLMProvider

        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = SimpleNamespace()

        provider = LiteLLMProvider()
        with patch("skillsaw.llm._litellm._get_litellm", return_value=mock_litellm):
            result = provider.complete(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                model="test-model",
            )

        assert result.content is None
        assert result.tool_calls == []
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0

    def test_missing_choices_attribute_preserves_usage(self):
        """Provider should preserve prompt usage even when choices attribute is missing."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from skillsaw.llm._litellm import LiteLLMProvider

        mock_litellm = MagicMock()
        usage = SimpleNamespace(prompt_tokens=55, completion_tokens=0)
        mock_litellm.completion.return_value = SimpleNamespace(usage=usage)

        provider = LiteLLMProvider()
        with patch("skillsaw.llm._litellm._get_litellm", return_value=mock_litellm):
            result = provider.complete(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                model="test-model",
            )

        assert result.content is None
        assert result.tool_calls == []
        assert result.usage.prompt_tokens == 55
        assert result.usage.completion_tokens == 0

    def test_invalid_json_tool_call_arguments(self):
        """Provider should handle invalid JSON in tool call arguments gracefully."""
        from unittest.mock import MagicMock, patch
        from skillsaw.llm._litellm import LiteLLMProvider

        mock_litellm = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_1"
        mock_tool_call.function.name = "read_file"
        mock_tool_call.function.arguments = "not valid json {{{{"

        mock_message.content = None
        mock_message.tool_calls = [mock_tool_call]
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_litellm.completion.return_value = mock_response

        provider = LiteLLMProvider()
        with patch("skillsaw.llm._litellm._get_litellm", return_value=mock_litellm):
            result = provider.complete(
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                model="test-model",
            )

        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "read_file"
        assert "_error" in tc.arguments
        assert "invalid JSON" in tc.arguments["_error"]
        assert tc.arguments["_raw"] == "not valid json {{{{"


class TestLLMConfigFromYaml:
    def test_llm_settings_in_config(self, tmp_path):
        from skillsaw.config import LinterConfig

        config_file = tmp_path / ".skillsaw.yaml"
        config_file.write_text(
            "llm:\n"
            "  model: gpt-4o\n"
            "  max_iterations: 5\n"
            "  max_tokens: 100000\n"
            "  confirm: false\n",
            encoding="utf-8",
        )
        config = LinterConfig.from_file(config_file)
        assert config.llm.model == "gpt-4o"
        assert config.llm.max_iterations == 5
        assert config.llm.max_tokens == 100000
        assert config.llm.confirm is False

    def test_llm_settings_defaults(self, tmp_path):
        from skillsaw.config import LinterConfig

        config_file = tmp_path / ".skillsaw.yaml"
        config_file.write_text("rules: {}\n", encoding="utf-8")
        config = LinterConfig.from_file(config_file)
        assert config.llm.model == ""
        assert config.llm.max_iterations == 10
        assert config.llm.confirm is True

    def test_env_override_in_settings(self, tmp_path, monkeypatch):
        from skillsaw.config import LinterConfig

        monkeypatch.setenv("SKILLSAW_MODEL", "custom-model")
        config_file = tmp_path / ".skillsaw.yaml"
        config_file.write_text("llm:\n  model: gpt-4o\n", encoding="utf-8")
        config = LinterConfig.from_file(config_file)
        assert config.llm.model == "custom-model"


class TestMaxIterationsCLIOverride:
    """Tests for --max-iterations CLI validation and override."""

    def test_max_iterations_zero_rejected(self, tmp_path):
        """--max-iterations 0 must be rejected with a clear error."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "fix",
                "--llm",
                "--max-iterations",
                "0",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "--max-iterations must be >= 1" in result.stderr

    def test_max_iterations_negative_rejected(self, tmp_path):
        """--max-iterations -1 must be rejected with a clear error."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "skillsaw",
                "fix",
                "--llm",
                "--max-iterations",
                "-1",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "--max-iterations must be >= 1" in result.stderr

    def test_max_iterations_positive_overrides_config(self):
        """--max-iterations with a positive value overrides the config default."""
        from argparse import Namespace
        from unittest.mock import patch

        from skillsaw.__main__ import _run_fix
        from skillsaw.config import LinterConfig

        config = LinterConfig.default()
        args = Namespace(
            path=Path("."),
            config=None,
            use_llm=True,
            model=None,
            max_iterations=5,
            all=False,
            yes=False,
            workers=None,
            dry_run=False,
        )

        with (
            patch("skillsaw.__main__.RepositoryContext"),
            patch("skillsaw.__main__.find_config", return_value=None),
            patch("skillsaw.__main__.LinterConfig.default", return_value=config),
            patch("skillsaw.__main__._require_llm_provider", side_effect=SystemExit(1)),
        ):
            try:
                _run_fix(args)
            except SystemExit:
                pass

        assert config.llm.max_iterations == 5

    def test_max_iterations_not_passed_keeps_default(self):
        """When --max-iterations is omitted, the config default is preserved."""
        from argparse import Namespace
        from unittest.mock import patch

        from skillsaw.__main__ import _run_fix
        from skillsaw.config import LinterConfig

        config = LinterConfig.default()
        default_value = config.llm.max_iterations
        args = Namespace(
            path=Path("."),
            config=None,
            use_llm=True,
            model=None,
            max_iterations=None,
            all=False,
            yes=False,
            workers=None,
            dry_run=False,
        )

        with (
            patch("skillsaw.__main__.RepositoryContext"),
            patch("skillsaw.__main__.find_config", return_value=None),
            patch("skillsaw.__main__.LinterConfig.default", return_value=config),
            patch("skillsaw.__main__._require_llm_provider", side_effect=SystemExit(1)),
        ):
            try:
                _run_fix(args)
            except SystemExit:
                pass

        assert config.llm.max_iterations == default_value


class TestContentRuleLLMPrompts:
    def test_weak_language_has_prompt(self):
        from skillsaw.rules.builtin.content_rules import ContentWeakLanguageRule

        rule = ContentWeakLanguageRule()
        assert rule.llm_fix_prompt is not None
        assert "weak" in rule.llm_fix_prompt.lower() or "hedging" in rule.llm_fix_prompt.lower()

    def test_tautological_has_prompt(self):
        from skillsaw.rules.builtin.content_rules import ContentTautologicalRule

        rule = ContentTautologicalRule()
        assert rule.llm_fix_prompt is not None
        assert "tautological" in rule.llm_fix_prompt.lower()

    def test_negative_only_has_prompt(self):
        from skillsaw.rules.builtin.content_rules import ContentNegativeOnlyRule

        rule = ContentNegativeOnlyRule()
        assert rule.llm_fix_prompt is not None
        assert "negative" in rule.llm_fix_prompt.lower()

    def test_base_rule_returns_none(self):
        from skillsaw.rules.builtin.command_format import CommandNamingRule

        rule = CommandNamingRule()
        assert rule.llm_fix_prompt is None


class TestLLMFixResult:
    def test_violations_fixed_calculation(self):
        from skillsaw.linter import LLMFixResult

        result = LLMFixResult(
            files_modified=[],
            violations_before=10,
            violations_after=3,
            total_usage=TokenUsage(0, 0),
            diffs={},
            success=True,
        )
        assert result.violations_fixed == 7

    def test_violations_fixed_no_improvement(self):
        from skillsaw.linter import LLMFixResult

        result = LLMFixResult(
            files_modified=[],
            violations_before=5,
            violations_after=5,
            total_usage=TokenUsage(0, 0),
            diffs={},
            success=False,
        )
        assert result.violations_fixed == 0


class TestLintToolExcludePatterns:
    """LintTool must honour config exclude_patterns."""

    def _make_skill(self, tmp_path):
        """Create a skill with a missing 'name' field so agentskill-valid fires."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\ndescription: a test skill\n---\n# My Skill\nDoes things.\n",
            encoding="utf-8",
        )
        return skill_md

    def test_lint_tool_respects_exclude_patterns(self, tmp_path):
        from skillsaw.config import LinterConfig
        from skillsaw.llm.tools import LintTool

        skill_md = self._make_skill(tmp_path)

        # Config with no excludes — the rule should fire.
        config_no_exclude = LinterConfig.default()
        config_no_exclude.version = "999.0.0"
        tool_no_exclude = LintTool(tmp_path, config_no_exclude, rule_ids={"agentskill-valid"})
        result_no_exclude = tool_no_exclude.execute(path="my-skill/SKILL.md")
        assert "Missing required 'name' field" in result_no_exclude

        # Config with an exclude pattern covering the skill directory.
        config_excluded = LinterConfig.default()
        config_excluded.version = "999.0.0"
        config_excluded.exclude_patterns = ["my-skill"]
        tool_excluded = LintTool(tmp_path, config_excluded, rule_ids={"agentskill-valid"})
        result_excluded = tool_excluded.execute(path="my-skill/SKILL.md")
        assert result_excluded == "No violations found."


class TestLintToolExceptionHandling:
    """LintTool.execute must surface rule exceptions, not swallow them."""

    def test_rule_exception_is_reported(self, tmp_path, monkeypatch):
        """When a rule's check() raises, the error must be returned to the LLM."""
        from skillsaw.config import LinterConfig
        from skillsaw.rule import Rule
        from skillsaw.context import RepositoryContext

        class ExplodingRule(Rule):
            rule_id = "test/exploding"
            name = "Exploding Rule"
            description = "Always raises"

            def default_severity(self):
                return Severity.ERROR

            def check(self, context: RepositoryContext):
                raise RuntimeError("kaboom")

        # Create a minimal file to lint
        target = tmp_path / "skill.md"
        target.write_text("---\ntitle: test\n---\n", encoding="utf-8")

        config_file = tmp_path / ".skillsaw.yaml"
        config_file.write_text("rules: {}\n", encoding="utf-8")
        config = LinterConfig.from_file(config_file)

        # Patch BUILTIN_RULES so only our exploding rule runs
        import skillsaw.rules.builtin as builtin_mod

        monkeypatch.setattr(builtin_mod, "BUILTIN_RULES", [ExplodingRule])

        tool = LintTool(tmp_path, config)
        result = tool.execute(path="skill.md")

        assert "Error running lint" in result
        assert "test/exploding" in result
        assert "kaboom" in result

    def test_rule_exception_not_swallowed_as_clean(self, tmp_path, monkeypatch):
        """Verify the result is NOT 'No violations found' when a rule crashes."""
        from skillsaw.config import LinterConfig
        from skillsaw.rule import Rule
        from skillsaw.context import RepositoryContext

        class BrokenRule(Rule):
            rule_id = "test/broken"
            name = "Broken Rule"
            description = "Always raises ValueError"

            def default_severity(self):
                return Severity.ERROR

            def check(self, context: RepositoryContext):
                raise ValueError("something went wrong")

        target = tmp_path / "skill.md"
        target.write_text("---\ntitle: test\n---\n", encoding="utf-8")

        config_file = tmp_path / ".skillsaw.yaml"
        config_file.write_text("rules: {}\n", encoding="utf-8")
        config = LinterConfig.from_file(config_file)

        import skillsaw.rules.builtin as builtin_mod

        monkeypatch.setattr(builtin_mod, "BUILTIN_RULES", [BrokenRule])

        tool = LintTool(tmp_path, config)
        result = tool.execute(path="skill.md")

        assert result != "No violations found."
        assert "Error running lint" in result
        assert "test/broken" in result
        assert "something went wrong" in result


class TestBlockState:
    def test_init_reads_body(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello world", encoding="utf-8")
        block = ContentBlock(path=f, category="instruction")
        state = BlockState(block)
        assert state.body == "hello world"
        assert state.original == "hello world"

    def test_body_mutation_independent(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("original", encoding="utf-8")
        block = ContentBlock(path=f, category="instruction")
        state = BlockState(block)
        state.body = "modified"
        assert state.original == "original"


class TestReadBlockTool:
    def test_returns_body(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content here", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = ReadBlockTool(state)
        assert tool.execute() == "content here"

    def test_returns_mutated_body(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("original", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        state.body = "modified"
        tool = ReadBlockTool(state)
        assert tool.execute() == "modified"

    def test_tool_metadata(self):
        assert ReadBlockTool.__dict__["name"] == "read_block"


class TestWriteBlockTool:
    def test_overwrites_body(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("old", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = WriteBlockTool(state)
        result = tool.execute(content="new content")
        assert "Updated block" in result
        assert state.body == "new content"
        assert state.original == "old"


class TestReplaceBlockSectionTool:
    def test_replace_unique(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Hello world", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = ReplaceBlockSectionTool(state)
        result = tool.execute(old_text="Hello", new_text="Goodbye")
        assert "Replaced 1 occurrence" in result
        assert state.body == "Goodbye world"

    def test_not_found(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Hello", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = ReplaceBlockSectionTool(state)
        result = tool.execute(old_text="missing", new_text="x")
        assert "Error: old_text not found" in result

    def test_multiple_matches(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("aaa bbb aaa", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = ReplaceBlockSectionTool(state)
        result = tool.execute(old_text="aaa", new_text="ccc")
        assert "found 2 times" in result


class TestDiffBlockTool:
    def test_shows_diff(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("line 1\nline 2\n", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        state.body = "line 1\nmodified\n"
        tool = DiffBlockTool(state)
        result = tool.execute()
        assert "-line 2" in result
        assert "+modified" in result

    def test_no_changes(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("unchanged\n", encoding="utf-8")
        state = BlockState(ContentBlock(path=f, category="instruction"))
        tool = DiffBlockTool(state)
        assert tool.execute() == "No changes."


class TestLintBlockTool:
    def test_no_violations(self, tmp_path):
        from skillsaw.config import LinterConfig

        f = tmp_path / "CLAUDE.md"
        (tmp_path / ".git").mkdir()
        f.write_text("# Instructions\n\nUse precise language.\n", encoding="utf-8")
        block = ContentBlock(path=f, category="claude-md")
        state = BlockState(block)
        config = LinterConfig.default()
        tool = LintBlockTool(state, config, root=tmp_path)
        result = tool.execute()
        assert result == "No violations found."

    def test_writes_body_to_disk(self, tmp_path):
        from skillsaw.config import LinterConfig

        f = tmp_path / "CLAUDE.md"
        (tmp_path / ".git").mkdir()
        f.write_text("original", encoding="utf-8")
        block = ContentBlock(path=f, category="claude-md")
        state = BlockState(block)
        state.body = "updated content"
        config = LinterConfig.default()
        tool = LintBlockTool(state, config, root=tmp_path)
        tool.execute()
        assert f.read_text(encoding="utf-8") == "updated content"
