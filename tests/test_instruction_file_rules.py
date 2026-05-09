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
    AgentsMdStructureRule,
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

    def test_gemini_md_in_subdirectory(self, temp_dir):
        sub = temp_dir / "backend"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("# Backend instructions\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_gemini_md_empty_in_subdirectory(self, temp_dir):
        sub = temp_dir / "frontend"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()
        assert violations[0].file_path == sub / "GEMINI.md"

    def test_gemini_md_invalid_encoding_in_subdirectory(self, temp_dir):
        sub = temp_dir / "lib"
        sub.mkdir()
        (sub / "GEMINI.md").write_bytes(b"\xff\xfe\x00\x80")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == sub / "GEMINI.md"

    def test_gemini_md_hierarchical_multiple_levels(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Root\n")
        sub = temp_dir / "src"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("# Src\n")
        deep = sub / "components"
        deep.mkdir()
        (deep / "GEMINI.md").write_text("# Components\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_gemini_md_hierarchical_mixed_valid_invalid(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Root instructions\n")
        sub = temp_dir / "api"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == sub / "GEMINI.md"

    def test_gemini_md_in_hidden_dir_skipped(self, temp_dir):
        hidden = temp_dir / ".hidden"
        hidden.mkdir()
        (hidden / "GEMINI.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_agents_md_not_discovered_in_subdirectory(self, temp_dir):
        sub = temp_dir / "sub"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0


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

    def test_import_to_existing_directory(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (temp_dir / "GEMINI.md").write_text("@docs\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_gemini_md_subdirectory_imports_resolved_relative(self, temp_dir):
        sub = temp_dir / "backend"
        sub.mkdir()
        helpers = sub / "helpers"
        helpers.mkdir()
        (helpers / "auth.md").write_text("# Auth helpers\n")
        (sub / "GEMINI.md").write_text("@helpers/auth.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_gemini_md_subdirectory_missing_import(self, temp_dir):
        sub = temp_dir / "backend"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("@missing/ref.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == sub / "GEMINI.md"
        assert "non-existent" in violations[0].message.lower()

    def test_gemini_md_subdirectory_import_escapes_root(self, temp_dir):
        sub = temp_dir / "deep" / "nested"
        sub.mkdir(parents=True)
        (sub / "GEMINI.md").write_text("@../../../etc/passwd\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "escapes" in violations[0].message.lower()

    def test_gemini_md_subdirectory_import_within_root_but_outside_subdir(self, temp_dir):
        (temp_dir / "shared.md").write_text("# Shared config\n")
        sub = temp_dir / "services" / "api"
        sub.mkdir(parents=True)
        (sub / "GEMINI.md").write_text("@../../shared.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_gemini_md_hierarchical_imports_multiple_levels(self, temp_dir):
        (temp_dir / "root-ref.md").write_text("# Root ref\n")
        (temp_dir / "GEMINI.md").write_text("@root-ref.md\n")
        sub = temp_dir / "pkg"
        sub.mkdir()
        (sub / "local.md").write_text("# Local\n")
        (sub / "GEMINI.md").write_text("@local.md\n@missing.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == sub / "GEMINI.md"
        assert "missing.md" in violations[0].message

    def test_gemini_md_in_hidden_dir_imports_skipped(self, temp_dir):
        hidden = temp_dir / ".config"
        hidden.mkdir()
        (hidden / "GEMINI.md").write_text("@nonexistent.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0


class TestAgentsMdStructureRule:
    def test_rule_metadata(self):
        rule = AgentsMdStructureRule()
        assert rule.rule_id == "agents-md-structure"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_agents_md_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_well_structured_agents_md_passes(self, temp_dir):
        content = "# Project Instructions\n\nFollow the coding standards below.\n\n## Style\n\nUse consistent formatting.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_no_headings_warns(self, temp_dir):
        content = "This file has no headings, just a block of text that is long enough to count as content.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 1
        assert "no markdown headings" in violations[0].message.lower()

    def test_headings_only_warns(self, temp_dir):
        content = "# Heading One\n\n## Heading Two\n\n"
        (temp_dir / "AGENTS.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 1
        assert "little content" in violations[0].message.lower()

    def test_empty_file_no_structure_violation(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_whitespace_only_no_structure_violation(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("   \n\n  \n")
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_invalid_encoding_no_structure_violation(self, temp_dir):
        (temp_dir / "AGENTS.md").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_single_heading_with_content_passes(self, temp_dir):
        content = "# Instructions\n\nHere are the instructions for this project.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 0

    def test_both_violations_no_heading_and_short_content(self, temp_dir):
        content = "short\n"
        (temp_dir / "AGENTS.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = AgentsMdStructureRule().check(context)
        assert len(violations) == 2
        messages = [v.message.lower() for v in violations]
        assert any("no markdown headings" in m for m in messages)
        assert any("little content" in m for m in messages)


class TestContextInstructionFiles:
    def test_no_instruction_files(self, temp_dir):
        context = RepositoryContext(temp_dir)
        assert context.instruction_files == []

    def test_agents_md_discovered(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\n")
        context = RepositoryContext(temp_dir)
        assert len(context.instruction_files) == 1
        assert context.instruction_files[0].name == "AGENTS.md"

    def test_all_instruction_files_discovered(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        (temp_dir / "GEMINI.md").write_text("# Gemini\n")
        context = RepositoryContext(temp_dir)
        names = [p.name for p in context.instruction_files]
        assert "AGENTS.md" in names
        assert "CLAUDE.md" in names
        assert "GEMINI.md" in names

    def test_order_preserved(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# A\n")
        (temp_dir / "GEMINI.md").write_text("# G\n")
        context = RepositoryContext(temp_dir)
        names = [p.name for p in context.instruction_files]
        assert names == ["AGENTS.md", "GEMINI.md"]
