"""Tests for inline suppression directives."""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.suppression import build_suppression_map, build_suppression_map_for_file
from skillsaw.linter import Linter
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# Unit tests for suppression map parsing
# ---------------------------------------------------------------------------


class TestBuildSuppressionMap:
    def test_disable_enable_pair(self):
        content = (
            "Line one\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
            "Try to handle errors again.\n"
        )
        smap = build_suppression_map(content)
        # Line 3 should be suppressed
        assert smap.is_suppressed("content-weak-language", 3)
        # Line 5 should NOT be suppressed (after enable)
        assert not smap.is_suppressed("content-weak-language", 5)
        # Other rules should not be suppressed
        assert not smap.is_suppressed("content-tautological", 3)

    def test_disable_next_line(self):
        content = (
            "Line one\n"
            "<!-- skillsaw-disable-next-line content-weak-language -->\n"
            "Try to handle errors.\n"
            "Try to handle errors again.\n"
        )
        smap = build_suppression_map(content)
        # Line 3 (the line after the directive) should be suppressed
        assert smap.is_suppressed("content-weak-language", 3)
        # Line 4 should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 4)

    def test_multiple_rules_in_directive(self):
        content = (
            "<!-- skillsaw-disable content-weak-language, content-tautological -->\n"
            "Try to write clean code.\n"
            "<!-- skillsaw-enable content-weak-language, content-tautological -->\n"
            "Try to write clean code again.\n"
        )
        smap = build_suppression_map(content)
        # Line 2 should be suppressed for both rules
        assert smap.is_suppressed("content-weak-language", 2)
        assert smap.is_suppressed("content-tautological", 2)
        # Line 4 should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 4)
        assert not smap.is_suppressed("content-tautological", 4)

    def test_unclosed_disable_suppresses_rest_of_file(self):
        content = (
            "Line one\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors.\n"
            "Try to handle more errors.\n"
            "Last line of file.\n"
        )
        smap = build_suppression_map(content)
        # All lines after the disable should be suppressed
        assert smap.is_suppressed("content-weak-language", 3)
        assert smap.is_suppressed("content-weak-language", 4)
        assert smap.is_suppressed("content-weak-language", 5)
        # Line 1 (before disable) should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 1)

    def test_enable_all(self):
        content = (
            "<!-- skillsaw-disable content-weak-language, content-tautological -->\n"
            "Suppressed line.\n"
            "<!-- skillsaw-enable -->\n"
            "Not suppressed.\n"
        )
        smap = build_suppression_map(content)
        # Line 2 suppressed for both
        assert smap.is_suppressed("content-weak-language", 2)
        assert smap.is_suppressed("content-tautological", 2)
        # Line 4 not suppressed for either (enable-all clears everything)
        assert not smap.is_suppressed("content-weak-language", 4)
        assert not smap.is_suppressed("content-tautological", 4)

    def test_enable_specific_leaves_others_disabled(self):
        content = (
            "<!-- skillsaw-disable content-weak-language, content-tautological -->\n"
            "Suppressed line.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
            "Only tautological suppressed.\n"
        )
        smap = build_suppression_map(content)
        # Line 4: content-weak-language should be re-enabled
        assert not smap.is_suppressed("content-weak-language", 4)
        # Line 4: content-tautological should still be disabled
        assert smap.is_suppressed("content-tautological", 4)

    def test_no_directives(self):
        content = "Line one\nLine two\nLine three\n"
        smap = build_suppression_map(content)
        assert not smap.is_suppressed("content-weak-language", 1)
        assert not smap.is_suppressed("content-weak-language", 2)
        assert not smap.is_suppressed("content-weak-language", 3)

    def test_disable_next_line_multiple_rules(self):
        content = (
            "<!-- skillsaw-disable-next-line content-weak-language, content-tautological -->\n"
            "Try to write clean code.\n"
            "Try to write clean code again.\n"
        )
        smap = build_suppression_map(content)
        assert smap.is_suppressed("content-weak-language", 2)
        assert smap.is_suppressed("content-tautological", 2)
        assert not smap.is_suppressed("content-weak-language", 3)
        assert not smap.is_suppressed("content-tautological", 3)

    def test_disable_all(self):
        """Bare <!-- skillsaw-disable --> should suppress all rules."""
        content = (
            "Line one\n"
            "<!-- skillsaw-disable -->\n"
            "Try to handle errors.\n"
            "This line is also suppressed.\n"
            "<!-- skillsaw-enable -->\n"
            "This line is not suppressed.\n"
        )
        smap = build_suppression_map(content)
        # Lines 3 and 4 should be suppressed for ANY rule
        assert smap.is_suppressed("content-weak-language", 3)
        assert smap.is_suppressed("content-tautological", 3)
        assert smap.is_suppressed("some-other-rule", 3)
        assert smap.is_suppressed("content-weak-language", 4)
        assert smap.is_suppressed("some-other-rule", 4)
        # Line 6 (after enable) should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 6)
        assert not smap.is_suppressed("some-other-rule", 6)
        # Line 1 (before disable) should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 1)

    def test_disable_all_unclosed(self):
        """Bare <!-- skillsaw-disable --> without enable suppresses rest of file."""
        content = "Line one\n" "<!-- skillsaw-disable -->\n" "Line three.\n" "Line four.\n"
        smap = build_suppression_map(content)
        assert not smap.is_suppressed("any-rule", 1)
        assert smap.is_suppressed("any-rule", 3)
        assert smap.is_suppressed("any-rule", 4)

    def test_disable_all_with_specific_rules(self):
        """Bare disable-all combined with specific disable/enable."""
        content = (
            "<!-- skillsaw-disable -->\n"
            "All suppressed.\n"
            "<!-- skillsaw-enable -->\n"
            "Not suppressed.\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Only weak-language suppressed.\n"
        )
        smap = build_suppression_map(content)
        # Line 2: all suppressed
        assert smap.is_suppressed("content-weak-language", 2)
        assert smap.is_suppressed("any-rule", 2)
        # Line 4: nothing suppressed
        assert not smap.is_suppressed("content-weak-language", 4)
        assert not smap.is_suppressed("any-rule", 4)
        # Line 6: only content-weak-language suppressed
        assert smap.is_suppressed("content-weak-language", 6)
        assert not smap.is_suppressed("any-rule", 6)

    def test_multiline_disable_enable(self):
        """Multi-line HTML comments should be parsed correctly."""
        content = (
            "Line one\n"
            "<!--\n"
            "    skillsaw-disable\n"
            "                       content-weak-language\n"
            "-->\n"
            "Try to handle errors.\n"
            "<!--\n"
            "    skillsaw-enable\n"
            "                       content-weak-language\n"
            "-->\n"
            "Try to handle errors again.\n"
        )
        smap = build_suppression_map(content)
        # Line 6 should be suppressed (between disable and enable)
        assert smap.is_suppressed("content-weak-language", 6)
        # Line 11 should NOT be suppressed (after enable)
        assert not smap.is_suppressed("content-weak-language", 11)
        # Other rules should not be suppressed
        assert not smap.is_suppressed("content-tautological", 6)

    def test_multiline_disable_next_line(self):
        """Multi-line disable-next-line should work."""
        content = (
            "Line one\n"
            "<!--\n"
            "    skillsaw-disable-next-line content-weak-language\n"
            "-->\n"
            "Try to handle errors.\n"
            "Try to handle errors again.\n"
        )
        smap = build_suppression_map(content)
        # Line 5 (the line after the closing -->) should be suppressed
        assert smap.is_suppressed("content-weak-language", 5)
        # Line 6 should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 6)

    def test_multiline_enable_all(self):
        """Multi-line enable-all should re-enable everything."""
        content = (
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Suppressed line.\n"
            "<!--\n"
            "    skillsaw-enable\n"
            "-->\n"
            "Not suppressed.\n"
        )
        smap = build_suppression_map(content)
        assert smap.is_suppressed("content-weak-language", 2)
        assert not smap.is_suppressed("content-weak-language", 6)

    def test_multiline_comment_with_extra_whitespace(self):
        """Multi-line comment with lots of whitespace should still parse."""
        content = (
            "Line one\n"
            "<!--\n"
            "    skillsaw-enable\n"
            "                       some-other-rule-->\n"
        )
        smap = build_suppression_map(content)
        # This is the exact example from the reviewer's comment.
        # The enable directive should parse correctly (it just enables a rule
        # that wasn't disabled, so it's a no-op, but it shouldn't crash).
        assert not smap.is_suppressed("some-other-rule", 1)

    def test_multiline_disable_multiple_rules(self):
        """Multi-line disable with multiple comma-separated rules."""
        content = (
            "<!--\n"
            "    skillsaw-disable\n"
            "        content-weak-language, content-tautological\n"
            "-->\n"
            "Suppressed for both rules.\n"
            "<!-- skillsaw-enable -->\n"
            "Not suppressed.\n"
        )
        smap = build_suppression_map(content)
        assert smap.is_suppressed("content-weak-language", 5)
        assert smap.is_suppressed("content-tautological", 5)
        assert not smap.is_suppressed("content-weak-language", 7)
        assert not smap.is_suppressed("content-tautological", 7)

    def test_multiline_bare_disable(self):
        """Multi-line bare disable (suppress all rules)."""
        content = (
            "Line one\n"
            "<!--\n"
            "    skillsaw-disable\n"
            "-->\n"
            "All suppressed.\n"
            "<!--\n"
            "    skillsaw-enable\n"
            "-->\n"
            "Not suppressed.\n"
        )
        smap = build_suppression_map(content)
        assert smap.is_suppressed("any-rule", 5)
        assert smap.is_suppressed("content-weak-language", 5)
        assert not smap.is_suppressed("any-rule", 9)

    def test_line_offset(self):
        """line_offset should shift all line numbers."""
        content = (
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
        )
        # With offset=5, the content lines become file lines 6, 7, 8
        smap = build_suppression_map(content, line_offset=5)
        # Line 7 (content line 2 + offset 5) should be suppressed
        assert smap.is_suppressed("content-weak-language", 7)
        # Line 2 (without offset) should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 2)
        # Line 9 (after enable) should NOT be suppressed
        assert not smap.is_suppressed("content-weak-language", 9)

    def test_nested_disable_enable(self):
        content = (
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Suppressed.\n"
            "<!-- skillsaw-disable content-tautological -->\n"
            "Both suppressed.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
            "Only tautological suppressed.\n"
            "<!-- skillsaw-enable content-tautological -->\n"
            "Nothing suppressed.\n"
        )
        smap = build_suppression_map(content)
        assert smap.is_suppressed("content-weak-language", 2)
        assert not smap.is_suppressed("content-tautological", 2)
        assert smap.is_suppressed("content-weak-language", 4)
        assert smap.is_suppressed("content-tautological", 4)
        assert not smap.is_suppressed("content-weak-language", 6)
        assert smap.is_suppressed("content-tautological", 6)
        assert not smap.is_suppressed("content-weak-language", 8)
        assert not smap.is_suppressed("content-tautological", 8)


class TestBuildSuppressionMapForFile:
    def test_reads_file(self, temp_dir):
        f = temp_dir / "test.md"
        f.write_text(
            "Line one\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors.\n"
        )
        smap = build_suppression_map_for_file(f)
        assert smap is not None
        assert smap.is_suppressed("content-weak-language", 3)
        assert not smap.is_suppressed("content-weak-language", 1)

    def test_nonexistent_file_returns_none(self, temp_dir):
        smap = build_suppression_map_for_file(temp_dir / "nonexistent.md")
        assert smap is None


# ---------------------------------------------------------------------------
# Integration tests: inline suppression with the linter
# ---------------------------------------------------------------------------


class TestInlineSuppressionIntegration:
    def test_disable_suppresses_violation(self, temp_dir):
        """Inline disable should suppress the violation"""
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors gracefully if possible.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
        )
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {"enabled": True, "severity": "warning"}
        linter = Linter(context, config)
        violations = linter.run()

        weak = [v for v in violations if v.rule_id == "content-weak-language"]
        assert len(weak) == 0

    def test_disable_next_line_suppresses_single_line(self, temp_dir):
        """disable-next-line should only suppress the immediately following line"""
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n"
            "<!-- skillsaw-disable-next-line content-weak-language -->\n"
            "Try to handle errors gracefully.\n"
            "Try to handle errors gracefully.\n"
        )
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {"enabled": True, "severity": "warning"}
        linter = Linter(context, config)
        violations = linter.run()

        weak = [v for v in violations if v.rule_id == "content-weak-language"]
        # Line 3 is suppressed, line 4 is NOT -- so we should still get violations from line 4
        assert len(weak) >= 1
        # Verify the surviving violations are from line 4 (file_line)
        for v in weak:
            assert v.file_line != 3

    def test_unsuppressed_violations_still_reported(self, temp_dir):
        """Violations outside suppression ranges should still be reported"""
        (temp_dir / "CLAUDE.md").write_text(
            "Try to handle errors gracefully.\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors gracefully.\n"
            "<!-- skillsaw-enable content-weak-language -->\n"
        )
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {"enabled": True, "severity": "warning"}
        linter = Linter(context, config)
        violations = linter.run()

        weak = [v for v in violations if v.rule_id == "content-weak-language"]
        # Line 1 is NOT suppressed, so violations from it should remain
        assert len(weak) >= 1

    def test_unclosed_disable_suppresses_rest_of_file(self, temp_dir):
        """An unclosed disable should suppress all remaining violations"""
        (temp_dir / "CLAUDE.md").write_text(
            "Clean line.\n"
            "<!-- skillsaw-disable content-weak-language -->\n"
            "Try to handle errors gracefully.\n"
            "You might want to add error handling.\n"
            "Consider using a try block.\n"
        )
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {"enabled": True, "severity": "warning"}
        linter = Linter(context, config)
        violations = linter.run()

        weak = [v for v in violations if v.rule_id == "content-weak-language"]
        assert len(weak) == 0

    def test_enable_all_reenables_everything(self, temp_dir):
        """enable-all should re-enable all previously disabled rules"""
        (temp_dir / "CLAUDE.md").write_text(
            "<!-- skillsaw-disable content-weak-language, content-tautological -->\n"
            "Try to write clean code.\n"
            "<!-- skillsaw-enable -->\n"
            "Try to write clean code.\n"
        )
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()
        config.rules["content-weak-language"] = {"enabled": True, "severity": "warning"}
        config.rules["content-tautological"] = {"enabled": True, "severity": "warning"}
        linter = Linter(context, config)
        violations = linter.run()

        # Line 2 should be suppressed, line 4 should NOT
        weak = [v for v in violations if v.rule_id == "content-weak-language"]
        taut = [v for v in violations if v.rule_id == "content-tautological"]
        # At least some violations from line 4
        assert len(weak) >= 1 or len(taut) >= 1
