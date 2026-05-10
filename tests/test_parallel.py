"""Tests for parallel execution and thread safety in the LLM fix pipeline."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

import pytest

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.llm._litellm import CompletionResult, ToolCall, TokenUsage
from skillsaw.llm.tools import ReadFileTool, WriteFileTool, ReplaceSectionTool, LintTool


class FakeProvider:
    def __init__(self, responses: List[CompletionResult]):
        self._responses = list(responses)
        self._idx = 0
        self._lock = threading.Lock()

    def complete(self, messages, tools, model, max_tokens=4096):
        with self._lock:
            if self._idx >= len(self._responses):
                return CompletionResult(content="Done.", tool_calls=[], usage=TokenUsage(10, 10))
            resp = self._responses[self._idx]
            self._idx += 1
            return resp


def _make_dot_claude_repo(tmp_path):
    """Create a repo with multiple files that have violations."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    (tmp_path / "CLAUDE.md").write_text(
        "# Rules\n\nTry to use consistent formatting.\nWrite clean code.\n",
        encoding="utf-8",
    )

    agents_dir = claude_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "helper.md").write_text(
        "---\nname: helper\ndescription: A helper agent\n---\n\n"
        "Consider using TypeScript for all new files.\n"
        "If possible, add tests.\n",
        encoding="utf-8",
    )

    return tmp_path


class TestParallelToolExecution:
    """Test that tools can be used concurrently without corruption."""

    def test_concurrent_reads(self, tmp_path):
        (tmp_path / "file1.md").write_text("content 1", encoding="utf-8")
        (tmp_path / "file2.md").write_text("content 2", encoding="utf-8")
        (tmp_path / "file3.md").write_text("content 3", encoding="utf-8")

        tool = ReadFileTool(tmp_path)
        results = {}
        errors = []

        def read_file(name):
            try:
                results[name] = tool.execute(path=name)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_file, args=(f"file{i}.md",)) for i in range(1, 4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert results["file1.md"] == "content 1"
        assert results["file2.md"] == "content 2"
        assert results["file3.md"] == "content 3"

    def test_concurrent_writes(self, tmp_path):
        tool = WriteFileTool(tmp_path)
        errors = []

        def write_file(name, content):
            try:
                tool.execute(path=name, content=content)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_file, args=(f"file{i}.md", f"content {i}"))
            for i in range(1, 6)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(1, 6):
            assert (tmp_path / f"file{i}.md").read_text() == f"content {i}"

    def test_concurrent_replace_different_files(self, tmp_path):
        for i in range(1, 4):
            (tmp_path / f"file{i}.md").write_text(f"old content {i}", encoding="utf-8")

        tool = ReplaceSectionTool(tmp_path)
        errors = []

        def replace_in_file(name, old, new):
            try:
                tool.execute(path=name, old_text=old, new_text=new)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=replace_in_file,
                args=(f"file{i}.md", f"old content {i}", f"new content {i}"),
            )
            for i in range(1, 4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(1, 4):
            assert (tmp_path / f"file{i}.md").read_text() == f"new content {i}"


class TestParallelLLMFix:
    """Test that llm_fix handles multiple files in parallel."""

    def test_multi_file_fix(self, tmp_path):
        _make_dot_claude_repo(tmp_path)
        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        violations = linter.run()
        fixable = [
            v
            for v in violations
            if v.rule_id in {r.rule_id for r in linter.rules if r.llm_fix_prompt}
        ]
        assert len(fixable) > 0

    def test_callback_thread_safety(self, tmp_path):
        """Verify the callback lock prevents interleaved output."""
        _make_dot_claude_repo(tmp_path)
        config = LinterConfig.default()
        context = RepositoryContext(tmp_path)
        linter = Linter(context, config)

        events = []
        lock = threading.Lock()

        def callback(event_type, **kw):
            with lock:
                events.append((event_type, dict(kw)))

        provider = FakeProvider(
            [
                CompletionResult(content="Done.", tool_calls=[], usage=TokenUsage(10, 10))
                for _ in range(20)
            ]
        )

        result = linter.llm_fix(provider, callback=callback, max_workers=2)
        progress_events = [e for e in events if e[0] == "progress"]
        assert len(progress_events) > 0

        # Verify ordering: each file's file_start must precede its file_done
        file_start_events = [e for e in events if e[0] == "file_start"]
        file_done_events = [e for e in events if e[0] == "file_done"]

        assert len(file_start_events) > 0, "Expected at least one file_start event"
        assert len(file_start_events) == len(
            file_done_events
        ), "Every file_start must have a corresponding file_done"

        # For each file, file_start must appear before file_done in the event list
        started_files = set()
        finished_files = set()
        for event_type, kw in events:
            if event_type not in {"file_start", "file_done"}:
                continue
            assert kw.get("rel_path"), f"{event_type} missing rel_path"
            rel_path = str(kw["rel_path"])
            if event_type == "file_start":
                assert rel_path not in started_files, f"Duplicate file_start for {rel_path}"
                started_files.add(rel_path)
            elif event_type == "file_done":
                assert (
                    rel_path in started_files
                ), f"file_done for {rel_path} without preceding file_start"
                assert rel_path not in finished_files, f"Duplicate file_done for {rel_path}"
                finished_files.add(rel_path)

        assert (
            started_files == finished_files
        ), f"Some files started but never finished: {started_files - finished_files}"

    def test_lint_tool_scoped_per_file(self, tmp_path):
        """Verify each file gets its own scoped LintTool."""
        _make_dot_claude_repo(tmp_path)
        config = LinterConfig.default()

        tool1 = LintTool(tmp_path, config, rule_ids={"content-weak-language"})
        tool2 = LintTool(tmp_path, config, rule_ids={"content-tautological"})

        result1 = tool1.execute(path="CLAUDE.md")
        result2 = tool2.execute(path="CLAUDE.md")

        assert result1 != result2 or "No violations" in result1


class TestParallelLintToolIsolation:
    """Test that LintTool instances don't interfere with each other."""

    def test_concurrent_lint_different_rules(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Rules\n\nTry to write clean code.\nWrite clean code.\n",
            encoding="utf-8",
        )
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        config = LinterConfig.default()
        results = {}
        errors = []

        def lint_with_rules(name, rule_ids):
            try:
                tool = LintTool(tmp_path, config, rule_ids=rule_ids)
                results[name] = tool.execute(path="CLAUDE.md")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(
                target=lint_with_rules,
                args=("weak", {"content-weak-language"}),
            ),
            threading.Thread(
                target=lint_with_rules,
                args=("taut", {"content-tautological"}),
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert "weak" in results
        assert "taut" in results
