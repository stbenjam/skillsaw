"""Tests for Copilot instruction file validation rules"""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.copilot_instructions import (
    CopilotInstructionsValidRule,
    CopilotDotInstructionsValidRule,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


class TestCopilotInstructionsValidRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsValidRule()
        assert rule.rule_id == "copilot-instructions-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_file_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_valid_file_passes(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_text(
            "# Copilot Instructions\nUse TypeScript.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_empty_file_fails(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_whitespace_only_file_fails(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_text("   \n\n  \n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_invalid_encoding_fails(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "copilot-instructions.md").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert (
            "encoding" in violations[0].message.lower() or "read" in violations[0].message.lower()
        )


class TestCopilotDotInstructionsValidRule:
    def test_rule_metadata(self):
        rule = CopilotDotInstructionsValidRule()
        assert rule.rule_id == "copilot-dot-instructions-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_files_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_valid_single_glob_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\n---\nUse type hints.\n'
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_valid_glob_list_passes(self, temp_dir):
        content = '---\napplyTo:\n  - "**/*.py"\n  - "**/*.js"\n---\nBe helpful.\n'
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_nested_instructions_file(self, temp_dir):
        subdir = temp_dir / "src" / "components"
        subdir.mkdir(parents=True)
        content = '---\napplyTo: "*.tsx"\n---\nUse React hooks.\n'
        (subdir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 0

    def test_empty_file_fails(self, temp_dir):
        (temp_dir / ".instructions.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_invalid_encoding_fails(self, temp_dir):
        (temp_dir / ".instructions.md").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert (
            "encoding" in violations[0].message.lower() or "read" in violations[0].message.lower()
        )

    def test_missing_frontmatter_fails(self, temp_dir):
        (temp_dir / ".instructions.md").write_text("Just some text without frontmatter.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "frontmatter" in violations[0].message.lower()

    def test_missing_apply_to_fails(self, temp_dir):
        content = "---\ntitle: Instructions\n---\nSome content.\n"
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "applyTo" in violations[0].message

    def test_apply_to_wrong_type_fails(self, temp_dir):
        content = "---\napplyTo: 42\n---\nSome content.\n"
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "string or list" in violations[0].message.lower()

    def test_apply_to_empty_pattern_fails(self, temp_dir):
        content = '---\napplyTo: ""\n---\nSome content.\n'
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "empty pattern" in violations[0].message.lower()

    def test_apply_to_list_with_non_string_fails(self, temp_dir):
        content = '---\napplyTo:\n  - "**/*.py"\n  - 42\n---\nContent.\n'
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert "non-string" in violations[0].message.lower()

    def test_apply_to_line_number_reported(self, temp_dir):
        content = "---\ntitle: Test\napplyTo: 42\n---\nContent.\n"
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_multiple_files_validated(self, temp_dir):
        (temp_dir / ".instructions.md").write_text("No frontmatter.\n")
        subdir = temp_dir / "src"
        subdir.mkdir()
        (subdir / ".instructions.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 2

    def test_valid_complex_globs_pass(self, temp_dir):
        content = '---\napplyTo:\n  - "src/**/*.{ts,tsx}"\n  - "tests/*.test.js"\n  - "docs/**"\n---\nInstructions.\n'
        (temp_dir / ".instructions.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CopilotDotInstructionsValidRule().check(context)
        assert len(violations) == 0
