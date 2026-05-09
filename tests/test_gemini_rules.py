"""Tests for GEMINI.md validation rules."""

import shutil
import tempfile
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.rule import AutofixConfidence, Severity
from skillsaw.rules.builtin.gemini import (
    GeminiCriticalPositionRule,
    GeminiDeadFileRefsRule,
    GeminiHierarchyConsistencyRule,
    GeminiImportCircularRule,
    GeminiImportDepthRule,
    GeminiImportValidRule,
    GeminiScopeFalsePositiveRule,
    GeminiSizeLimitRule,
    GeminiTautologicalRule,
    GeminiWeakLanguageRule,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# gemini-import-valid
# ---------------------------------------------------------------------------


class TestGeminiImportValidRule:
    def test_rule_metadata(self):
        rule = GeminiImportValidRule()
        assert rule.rule_id == "gemini-import-valid"
        assert rule.default_severity() == Severity.WARNING

    def test_no_gemini_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        assert GeminiImportValidRule().check(context) == []

    def test_valid_import(self, temp_dir):
        (temp_dir / "docs.md").write_text("# Docs\n")
        (temp_dir / "GEMINI.md").write_text("@docs.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportValidRule().check(context) == []

    def test_missing_import(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@missing.md\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiImportValidRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message
        assert violations[0].line == 1

    def test_directory_import(self, temp_dir):
        (temp_dir / "docs").mkdir()
        (temp_dir / "GEMINI.md").write_text("@docs\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportValidRule().check(context) == []

    def test_escape_root(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@../../etc/passwd\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiImportValidRule().check(context)
        assert len(violations) == 1
        assert "escapes" in violations[0].message

    def test_scoped_package_skipped(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@angular/core\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportValidRule().check(context) == []

    def test_subdirectory_import(self, temp_dir):
        sub = temp_dir / "backend"
        sub.mkdir()
        helpers = sub / "helpers"
        helpers.mkdir()
        (helpers / "auth.md").write_text("# Auth\n")
        (sub / "GEMINI.md").write_text("@helpers/auth.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportValidRule().check(context) == []


# ---------------------------------------------------------------------------
# gemini-import-circular
# ---------------------------------------------------------------------------


class TestGeminiImportCircularRule:
    def test_rule_metadata(self):
        rule = GeminiImportCircularRule()
        assert rule.rule_id == "gemini-import-circular"
        assert rule.default_severity() == Severity.ERROR

    def test_no_imports_no_violations(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Instructions\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportCircularRule().check(context) == []

    def test_direct_cycle(self, temp_dir):
        a = temp_dir / "a.md"
        b = temp_dir / "b.md"
        a.write_text("@b.md\n")
        b.write_text("@a.md\n")
        (temp_dir / "GEMINI.md").write_text("@a.md\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiImportCircularRule().check(context)
        assert len(violations) >= 1
        assert "circular" in violations[0].message.lower()

    def test_transitive_cycle(self, temp_dir):
        a = temp_dir / "a.md"
        b = temp_dir / "b.md"
        c = temp_dir / "c.md"
        a.write_text("@b.md\n")
        b.write_text("@c.md\n")
        c.write_text("@a.md\n")
        (temp_dir / "GEMINI.md").write_text("@a.md\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiImportCircularRule().check(context)
        assert len(violations) >= 1
        assert "circular" in violations[0].message.lower()

    def test_no_cycle(self, temp_dir):
        a = temp_dir / "a.md"
        b = temp_dir / "b.md"
        a.write_text("@b.md\n")
        b.write_text("# End\n")
        (temp_dir / "GEMINI.md").write_text("@a.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportCircularRule().check(context) == []


# ---------------------------------------------------------------------------
# gemini-import-depth
# ---------------------------------------------------------------------------


class TestGeminiImportDepthRule:
    def test_rule_metadata(self):
        rule = GeminiImportDepthRule()
        assert rule.rule_id == "gemini-import-depth"
        assert rule.default_severity() == Severity.WARNING

    def test_shallow_chain_ok(self, temp_dir):
        a = temp_dir / "a.md"
        b = temp_dir / "b.md"
        a.write_text("@b.md\n")
        b.write_text("# End\n")
        (temp_dir / "GEMINI.md").write_text("@a.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportDepthRule().check(context) == []

    def test_deep_chain_warns(self, temp_dir):
        prev = None
        for i in range(7):
            f = temp_dir / f"level{i}.md"
            if i < 6:
                f.write_text(f"@level{i+1}.md\n")
            else:
                f.write_text("# End\n")
            prev = f
        (temp_dir / "GEMINI.md").write_text("@level0.md\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiImportDepthRule().check(context)
        assert len(violations) >= 1
        assert "depth" in violations[0].message.lower()

    def test_exactly_5_no_violation(self, temp_dir):
        for i in range(5):
            f = temp_dir / f"l{i}.md"
            if i < 4:
                f.write_text(f"@l{i+1}.md\n")
            else:
                f.write_text("# End\n")
        (temp_dir / "GEMINI.md").write_text("@l0.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiImportDepthRule().check(context) == []


# ---------------------------------------------------------------------------
# gemini-scope-false-positive
# ---------------------------------------------------------------------------


class TestGeminiScopeFalsePositiveRule:
    def test_rule_metadata(self):
        rule = GeminiScopeFalsePositiveRule()
        assert rule.rule_id == "gemini-scope-false-positive"
        assert rule.default_severity() == Severity.WARNING
        assert rule.supports_autofix

    def test_scoped_package_detected(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@angular/core\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiScopeFalsePositiveRule().check(context)
        assert len(violations) == 1
        assert "npm scoped package" in violations[0].message

    def test_real_import_not_flagged(self, temp_dir):
        (temp_dir / "docs.md").write_text("# Docs\n")
        (temp_dir / "GEMINI.md").write_text("@docs.md\n")
        context = RepositoryContext(temp_dir)
        assert GeminiScopeFalsePositiveRule().check(context) == []

    def test_scoped_package_at_real_path_not_flagged(self, temp_dir):
        # If the actual file exists at the resolved path (without @), no warning
        myorg = temp_dir / "myorg"
        myorg.mkdir()
        mylib = myorg / "mylib"
        mylib.mkdir()
        (temp_dir / "GEMINI.md").write_text("@myorg/mylib\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiScopeFalsePositiveRule().check(context)
        assert len(violations) == 0

    def test_autofix_wraps_in_backticks(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@angular/core\n")
        context = RepositoryContext(temp_dir)
        rule = GeminiScopeFalsePositiveRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "`@angular/core`" in fixes[0].fixed_content
        assert fixes[0].confidence == AutofixConfidence.SAFE


# ---------------------------------------------------------------------------
# gemini-hierarchy-consistency
# ---------------------------------------------------------------------------


class TestGeminiHierarchyConsistencyRule:
    def test_rule_metadata(self):
        rule = GeminiHierarchyConsistencyRule()
        assert rule.rule_id == "gemini-hierarchy-consistency"
        assert rule.default_severity() == Severity.WARNING

    def test_single_file_no_violations(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Setup\n\nDo stuff.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiHierarchyConsistencyRule().check(context) == []

    def test_different_headings_ok(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Project Setup\n\nGlobal config.\n")
        sub = temp_dir / "api"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("# API Rules\n\nAPI-specific.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiHierarchyConsistencyRule().check(context) == []

    def test_overlapping_headings_warns(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Setup\n## Testing\n\nContent.\n")
        sub = temp_dir / "lib"
        sub.mkdir()
        (sub / "GEMINI.md").write_text("# Testing\n\nDuplicate.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiHierarchyConsistencyRule().check(context)
        assert len(violations) == 1
        assert "testing" in violations[0].message.lower()

    def test_no_gemini_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        assert GeminiHierarchyConsistencyRule().check(context) == []


# ---------------------------------------------------------------------------
# gemini-size-limit
# ---------------------------------------------------------------------------


class TestGeminiSizeLimitRule:
    def test_rule_metadata(self):
        rule = GeminiSizeLimitRule()
        assert rule.rule_id == "gemini-size-limit"
        assert rule.default_severity() == Severity.WARNING

    def test_small_file_ok(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Short\n\nBrief.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiSizeLimitRule().check(context) == []

    def test_warn_threshold(self, temp_dir):
        lines = ["# Instructions\n"] + [f"Rule {i}\n" for i in range(160)]
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        violations = GeminiSizeLimitRule().check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING

    def test_error_threshold(self, temp_dir):
        lines = ["# Instructions\n"] + [f"Rule {i}\n" for i in range(510)]
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        violations = GeminiSizeLimitRule().check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR

    def test_custom_thresholds(self, temp_dir):
        lines = ["line\n"] * 25
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        rule = GeminiSizeLimitRule({"warn_lines": 20, "error_lines": 100})
        violations = rule.check(context)
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# gemini-dead-file-refs
# ---------------------------------------------------------------------------


class TestGeminiDeadFileRefsRule:
    def test_rule_metadata(self):
        rule = GeminiDeadFileRefsRule()
        assert rule.rule_id == "gemini-dead-file-refs"
        assert rule.default_severity() == Severity.WARNING

    def test_no_refs_ok(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Instructions\n\nPlain text.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiDeadFileRefsRule().check(context) == []

    def test_valid_ref_ok(self, temp_dir):
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("# main\n")
        (temp_dir / "GEMINI.md").write_text("See src/main.py for details.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiDeadFileRefsRule().check(context) == []

    def test_dead_ref_warns(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("See src/missing.py for details.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiDeadFileRefsRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message

    def test_code_block_skipped(self, temp_dir):
        content = "```\nsrc/missing.py\n```\n"
        (temp_dir / "GEMINI.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = GeminiDeadFileRefsRule().check(context)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# gemini-weak-language
# ---------------------------------------------------------------------------


class TestGeminiWeakLanguageRule:
    def test_rule_metadata(self):
        rule = GeminiWeakLanguageRule()
        assert rule.rule_id == "gemini-weak-language"
        assert rule.default_severity() == Severity.INFO
        assert rule.supports_autofix

    def test_no_weak_language_ok(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Rules\n\nAlways use snake_case.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiWeakLanguageRule().check(context) == []

    def test_weak_phrase_detected(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("Try to use consistent naming.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiWeakLanguageRule().check(context)
        assert len(violations) == 1
        assert "try to" in violations[0].message.lower()

    def test_multiple_weak_phrases(self, temp_dir):
        content = "Maybe use TypeScript.\nConsider adding tests.\n"
        (temp_dir / "GEMINI.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = GeminiWeakLanguageRule().check(context)
        assert len(violations) == 2

    def test_autofix_returns_suggest(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("Try to format code.\n")
        context = RepositoryContext(temp_dir)
        rule = GeminiWeakLanguageRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST


# ---------------------------------------------------------------------------
# gemini-tautological
# ---------------------------------------------------------------------------


class TestGeminiTautologicalRule:
    def test_rule_metadata(self):
        rule = GeminiTautologicalRule()
        assert rule.rule_id == "gemini-tautological"
        assert rule.default_severity() == Severity.INFO
        assert rule.supports_autofix

    def test_no_tautology_ok(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Rules\n\nUse Python 3.12.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiTautologicalRule().check(context) == []

    def test_you_are_ai_detected(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("You are an AI assistant.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiTautologicalRule().check(context)
        assert len(violations) == 1
        assert "tautological" in violations[0].message.lower()

    def test_be_helpful_detected(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("Be helpful when answering.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiTautologicalRule().check(context)
        assert len(violations) == 1

    def test_autofix_removes_line(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Rules\nYou are an AI.\nUse Python.\n")
        context = RepositoryContext(temp_dir)
        rule = GeminiTautologicalRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "You are an AI" not in fixes[0].fixed_content
        assert "Use Python" in fixes[0].fixed_content
        assert fixes[0].confidence == AutofixConfidence.SAFE

    def test_respond_in_english_detected(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("Respond in English.\n")
        context = RepositoryContext(temp_dir)
        violations = GeminiTautologicalRule().check(context)
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# gemini-critical-position
# ---------------------------------------------------------------------------


class TestGeminiCriticalPositionRule:
    def test_rule_metadata(self):
        rule = GeminiCriticalPositionRule()
        assert rule.rule_id == "gemini-critical-position"
        assert rule.default_severity() == Severity.INFO
        assert rule.supports_autofix

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("CRITICAL: do this.\n")
        context = RepositoryContext(temp_dir)
        assert GeminiCriticalPositionRule().check(context) == []

    def test_critical_at_top_ok(self, temp_dir):
        lines = ["CRITICAL: do this.\n"] + [f"Rule {i}\n" for i in range(30)]
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        assert GeminiCriticalPositionRule().check(context) == []

    def test_critical_at_bottom_warns(self, temp_dir):
        lines = [f"Rule {i}\n" for i in range(30)] + ["CRITICAL: do this.\n"]
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        violations = GeminiCriticalPositionRule().check(context)
        assert len(violations) == 1
        assert "critical" in violations[0].message.lower()

    def test_autofix_returns_suggest(self, temp_dir):
        lines = [f"Rule {i}\n" for i in range(30)] + ["MUST do this.\n"]
        (temp_dir / "GEMINI.md").write_text("".join(lines))
        context = RepositoryContext(temp_dir)
        rule = GeminiCriticalPositionRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
