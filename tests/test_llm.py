"""Tests for the LLM-as-judge autofix engine."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import pytest

from skillsaw.llm._litellm import CompletionResult, ToolCall, TokenUsage
from skillsaw.llm.config import EngineConfig
from skillsaw.llm.engine import LLMEngine, LLMResult, ToolCallRecord
from skillsaw.llm.tools import (
    ReadFileTool,
    WriteFileTool,
    ReplaceSectionTool,
    DiffTool,
)
from skillsaw.rule import AutofixConfidence


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


class TestEngineConfig:
    def test_defaults(self):
        config = EngineConfig()
        assert config.model == ""
        assert config.max_tokens == 4096
        assert config.max_iterations == 5
        assert config.max_total_tokens == 500_000

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SKILLSAW_MODEL", "gpt-4o")
        config = EngineConfig()
        assert config.model == "gpt-4o"

    def test_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SKILLSAW_MODEL", raising=False)
        config = EngineConfig()
        assert config.model == ""


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
        config = EngineConfig(max_total_tokens=100)
        provider = FakeProvider(
            [
                CompletionResult(
                    content=None,
                    tool_calls=[ToolCall(id="call_1", name="unknown", arguments={})],
                    usage=TokenUsage(80, 30),
                ),
            ]
        )
        engine = LLMEngine(provider, [], config)
        result = engine.run("system", "user")
        # Budget check happens at start of next iteration, so we get 2 iterations
        assert result.iterations == 2
        assert result.budget_exhausted

    def test_max_iterations(self):
        config = EngineConfig(max_iterations=2)
        responses = [
            CompletionResult(
                content=None,
                tool_calls=[ToolCall(id=f"call_{i}", name="unknown", arguments={})],
                usage=TokenUsage(10, 10),
            )
            for i in range(5)
        ]
        provider = FakeProvider(responses)
        engine = LLMEngine(provider, [], config)
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
