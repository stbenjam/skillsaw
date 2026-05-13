"""Tests for instruction file validation rules (AGENTS.md, CLAUDE.md, GEMINI.md)"""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.instruction_files import (
    InstructionFileValidRule,
    InstructionImportsValidRule,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


class TestInstructionFileValidRule:
    def test_rule_metadata(self):
        rule = InstructionFileValidRule()
        assert rule.rule_id == "instruction-file-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_instruction_files_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_agents_md_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\nDo stuff.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_claude_md_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\nBe helpful.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_gemini_md_passes(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Gemini\nInstructions here.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_all_three_valid_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        (temp_dir / "GEMINI.md").write_text("# Gemini\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_empty_file_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_whitespace_only_file_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("   \n\n  \n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_invalid_encoding_fails(self, temp_dir):
        (temp_dir / "GEMINI.md").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert (
            "read" in violations[0].message.lower() or "encoding" in violations[0].message.lower()
        )


class TestInstructionImportsValidRule:
    def test_rule_metadata(self):
        rule = InstructionImportsValidRule()
        assert rule.rule_id == "instruction-imports-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_no_imports_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\nJust plain text.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_valid_import_passes(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/setup.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_missing_import_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/missing.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message.lower()
        assert violations[0].line == 3

    def test_multiple_imports_mixed(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "exists.md").write_text("# Exists\n")
        content = "# Instructions\n@docs/exists.md\n@docs/missing.md\n@also/gone.md\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 2
        messages = [v.message for v in violations]
        assert any("missing.md" in m for m in messages)
        assert any("gone.md" in m for m in messages)

    def test_import_line_number_accurate(self, temp_dir):
        content = "line 1\nline 2\nline 3\nline 4\n@nonexistent.md\nline 6\n"
        (temp_dir / "GEMINI.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 5

    def test_gemini_md_imports_checked(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@missing-file.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1

    def test_agents_md_imports_not_checked(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("@some-reference.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_import_escapes_repo_root(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("@../../etc/passwd\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "escapes" in violations[0].message.lower()

    def test_import_with_leading_whitespace(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("  @nonexistent.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1

    def test_inline_at_not_matched(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Contact user@example.com for help\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_in_fenced_code_block_not_matched(self, temp_dir):
        content = (
            "# Instructions\n"
            "\n"
            "```python\n"
            "import functools\n"
            "\n"
            "class MyService:\n"
            "    @functools.lru_cache(maxsize=128)\n"
            "    def fetch_data(self, key: str) -> dict:\n"
            "        ...\n"
            "```\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_import_in_fenced_code_block_not_matched(self, temp_dir):
        content = (
            "# Instructions\n"
            "\n"
            "Example import syntax:\n"
            "\n"
            "```\n"
            "@docs/setup.md\n"
            "```\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_import_outside_fenced_block_still_checked(self, temp_dir):
        content = (
            "# Instructions\n" "\n" "```python\n" "@decorator\n" "```\n" "\n" "@nonexistent.md\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 7

    def test_import_to_existing_directory(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (temp_dir / "GEMINI.md").write_text("@docs\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0
