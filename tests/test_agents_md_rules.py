"""Tests for deep AGENTS.md validation rules."""

import json
import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import AutofixConfidence, Severity
from skillsaw.rules.builtin.agents_md import (
    AgentsMdSizeLimitRule,
    AgentsMdOverrideSemanticsRule,
    AgentsMdHierarchyConsistencyRule,
    AgentsMdDeadFileRefsRule,
    AgentsMdDeadCommandRefsRule,
    AgentsMdWeakLanguageRule,
    AgentsMdNegativeOnlyRule,
    AgentsMdSectionLengthRule,
    AgentsMdStructureDeepRule,
    AgentsMdTautologicalRule,
    AgentsMdCriticalPositionRule,
    AgentsMdHookCandidateRule,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. agents-md-size-limit
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdSizeLimitRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdSizeLimitRule().check(ctx) == []

    def test_small_file_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\nDo stuff.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdSizeLimitRule().check(ctx) == []

    def test_warn_at_24kb(self, temp_dir):
        content = "x" * 25000
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdSizeLimitRule().check(ctx)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "approaching" in violations[0].message

    def test_error_at_32kb(self, temp_dir):
        content = "x" * 33000
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdSizeLimitRule().check(ctx)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert "exceeds" in violations[0].message

    def test_utf8_multibyte_counted(self, temp_dir):
        content = "é" * 13000
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdSizeLimitRule().check(ctx)
        assert len(violations) == 1

    def test_custom_thresholds(self, temp_dir):
        content = "x" * 500
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        rule = AgentsMdSizeLimitRule({"warn_bytes": 100, "error_bytes": 1000})
        violations = rule.check(ctx)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING

    def test_metadata(self):
        rule = AgentsMdSizeLimitRule()
        assert rule.rule_id == "agents-md-size-limit"
        assert rule.default_severity() == Severity.WARNING


# ═══════════════════════════════════════════════════════════════════════════════
# 2. agents-md-override-semantics
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdOverrideSemanticsRule:
    def test_no_override_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdOverrideSemanticsRule().check(ctx) == []

    def test_override_exists_warns(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\n")
        (temp_dir / "AGENTS.override.md").write_text("# Override\nNew rules.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdOverrideSemanticsRule().check(ctx)
        assert len(violations) >= 1
        assert "REPLACES" in violations[0].message

    def test_override_references_agents_md(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\n## Style\nUse black.\n")
        (temp_dir / "AGENTS.override.md").write_text(
            "# Override\nSee AGENTS.md for the base rules.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdOverrideSemanticsRule().check(ctx)
        ref_violations = [v for v in violations if "references AGENTS.md" in v.message]
        assert len(ref_violations) >= 1

    def test_override_without_base_warns(self, temp_dir):
        (temp_dir / "AGENTS.override.md").write_text("# Override\nDo things.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdOverrideSemanticsRule().check(ctx)
        assert len(violations) >= 1

    def test_metadata(self):
        rule = AgentsMdOverrideSemanticsRule()
        assert rule.rule_id == "agents-md-override-semantics"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. agents-md-hierarchy-consistency
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdHierarchyConsistencyRule:
    def test_no_subdir_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Project\n- Use pytest\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdHierarchyConsistencyRule().check(ctx) == []

    def test_consistent_subdir_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Project\n- Use pytest\n")
        sub = temp_dir / "backend"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("# Backend\n- Use pytest\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdHierarchyConsistencyRule().check(ctx) == []

    def test_contradicting_subdir_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Root\n- Use pytest\n")
        sub = temp_dir / "tests"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("# Tests\n- Use unittest\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdHierarchyConsistencyRule().check(ctx)
        assert len(violations) >= 1
        assert "Contradicts" in violations[0].message

    def test_no_root_agents_passes(self, temp_dir):
        sub = temp_dir / "lib"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("# Lib\n- Use unittest\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdHierarchyConsistencyRule().check(ctx) == []

    def test_metadata(self):
        rule = AgentsMdHierarchyConsistencyRule()
        assert rule.rule_id == "agents-md-hierarchy-consistency"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. agents-md-dead-file-refs
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdDeadFileRefsRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadFileRefsRule().check(ctx) == []

    def test_valid_refs_pass(self, temp_dir):
        src = temp_dir / "src"
        src.mkdir()
        (src / "main.py").write_text("print('hi')")
        (temp_dir / "AGENTS.md").write_text("# Code\nSee `src/main.py` for entry point.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadFileRefsRule().check(ctx) == []

    def test_dead_ref_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Code\nSee `src/missing.py` for entry point.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdDeadFileRefsRule().check(ctx)
        assert len(violations) == 1
        assert "src/missing.py" in violations[0].message
        assert violations[0].line == 2

    def test_path_traversal_skipped(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Code\nSee `../../etc/passwd` for config.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdDeadFileRefsRule().check(ctx)
        assert len(violations) == 0

    def test_markdown_link_ref(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("Read the [guide](./docs/guide.md)\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdDeadFileRefsRule().check(ctx)
        assert len(violations) == 1
        assert "docs/guide.md" in violations[0].message

    def test_valid_markdown_link(self, temp_dir):
        docs = temp_dir / "docs"
        docs.mkdir()
        (docs / "guide.md").write_text("# Guide")
        (temp_dir / "AGENTS.md").write_text("Read the [guide](./docs/guide.md)\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadFileRefsRule().check(ctx) == []

    def test_metadata(self):
        rule = AgentsMdDeadFileRefsRule()
        assert rule.rule_id == "agents-md-dead-file-refs"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. agents-md-dead-command-refs
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdDeadCommandRefsRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadCommandRefsRule().check(ctx) == []

    def test_valid_npm_script(self, temp_dir):
        (temp_dir / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        (temp_dir / "AGENTS.md").write_text("Run `npm run test` before committing.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadCommandRefsRule().check(ctx) == []

    def test_dead_npm_script(self, temp_dir):
        (temp_dir / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        (temp_dir / "AGENTS.md").write_text("Run `npm run missing-script` to verify.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdDeadCommandRefsRule().check(ctx)
        assert len(violations) == 1
        assert "missing-script" in violations[0].message

    def test_valid_make_target(self, temp_dir):
        (temp_dir / "Makefile").write_text("build:\n\tgo build ./...\n")
        (temp_dir / "AGENTS.md").write_text("Run `make build` to compile.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadCommandRefsRule().check(ctx) == []

    def test_dead_make_target(self, temp_dir):
        (temp_dir / "Makefile").write_text("build:\n\tgo build ./...\n")
        (temp_dir / "AGENTS.md").write_text("Run `make deploy` to deploy.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdDeadCommandRefsRule().check(ctx)
        assert len(violations) == 1
        assert "deploy" in violations[0].message

    def test_no_package_json_skips(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("Run `npm run test` first.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdDeadCommandRefsRule().check(ctx) == []

    def test_metadata(self):
        rule = AgentsMdDeadCommandRefsRule()
        assert rule.rule_id == "agents-md-dead-command-refs"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. agents-md-weak-language
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdWeakLanguageRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdWeakLanguageRule().check(ctx) == []

    def test_clean_file_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nRun tests before committing.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdWeakLanguageRule().check(ctx) == []

    def test_weak_phrases_detected(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(
            "# Instructions\nBe careful with imports.\nTry to follow conventions.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdWeakLanguageRule().check(ctx)
        assert len(violations) >= 2
        phrases = [v.message for v in violations]
        assert any("be careful" in p for p in phrases)
        assert any("try to" in p for p in phrases)

    def test_deduplication(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nBe careful here.\nBe careful there.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdWeakLanguageRule().check(ctx)
        assert len(violations) == 1

    def test_has_autofix(self):
        rule = AgentsMdWeakLanguageRule()
        assert rule.supports_autofix is True

    def test_fix_returns_suggest(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nTry to use black.\n")
        ctx = RepositoryContext(temp_dir)
        rule = AgentsMdWeakLanguageRule()
        violations = rule.check(ctx)
        fixes = rule.fix(ctx, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST

    def test_metadata(self):
        rule = AgentsMdWeakLanguageRule()
        assert rule.rule_id == "agents-md-weak-language"
        assert rule.default_severity() == Severity.INFO


# ═══════════════════════════════════════════════════════════════════════════════
# 7. agents-md-negative-only
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdNegativeOnlyRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdNegativeOnlyRule().check(ctx) == []

    def test_negative_with_alternative_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nNever use var — use const or let instead.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdNegativeOnlyRule().check(ctx) == []

    def test_negative_without_alternative_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nNever use var.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdNegativeOnlyRule().check(ctx)
        assert len(violations) == 1
        assert "alternative" in violations[0].message.lower()

    def test_dont_without_alternative_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nDon't use console.log.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdNegativeOnlyRule().check(ctx)
        assert len(violations) == 1

    def test_metadata(self):
        rule = AgentsMdNegativeOnlyRule()
        assert rule.rule_id == "agents-md-negative-only"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. agents-md-section-length
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdSectionLengthRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdSectionLengthRule().check(ctx) == []

    def test_short_sections_pass(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# A\nShort.\n\n# B\nAlso short.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdSectionLengthRule().check(ctx) == []

    def test_long_section_fails(self, temp_dir):
        lines = ["# Long Section"] + [f"Line {i}" for i in range(60)]
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdSectionLengthRule().check(ctx)
        assert len(violations) == 1
        assert "Long Section" in violations[0].message
        assert "lost-in-the-middle" in violations[0].message

    def test_custom_max_lines(self, temp_dir):
        lines = ["# Section"] + [f"Line {i}" for i in range(15)]
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        rule = AgentsMdSectionLengthRule({"max_lines": 10})
        violations = rule.check(ctx)
        assert len(violations) == 1

    def test_metadata(self):
        rule = AgentsMdSectionLengthRule()
        assert rule.rule_id == "agents-md-section-length"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. agents-md-structure-deep
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdStructureDeepRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdStructureDeepRule().check(ctx) == []

    def test_well_structured_passes(self, temp_dir):
        content = (
            "# Project\n\n"
            "## When writing tests\nUse pytest.\n\n"
            "## When reviewing PRs\nCheck coverage.\n\n"
            "## Always\nRun linter.\n"
        )
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdStructureDeepRule().check(ctx) == []

    def test_no_when_headings_warns(self, temp_dir):
        content = "# Project\n\n## Setup\nDo X.\n\n## Testing\nDo Y.\n\n## Deploy\nDo Z.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdStructureDeepRule().check(ctx)
        assert any("When" in v.message for v in violations)

    def test_no_boundary_headings_warns(self, temp_dir):
        content = "# Project\n\n## When A\nDo X.\n\n## When B\nDo Y.\n\n## When C\nDo Z.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdStructureDeepRule().check(ctx)
        assert any("boundary" in v.message.lower() for v in violations)

    def test_has_autofix(self):
        rule = AgentsMdStructureDeepRule()
        assert rule.supports_autofix is True

    def test_metadata(self):
        rule = AgentsMdStructureDeepRule()
        assert rule.rule_id == "agents-md-structure-deep"
        assert rule.default_severity() == Severity.INFO


# ═══════════════════════════════════════════════════════════════════════════════
# 10. agents-md-tautological
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdTautologicalRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdTautologicalRule().check(ctx) == []

    def test_clean_file_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nRun pytest with -x flag.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdTautologicalRule().check(ctx) == []

    def test_tautological_detected(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(
            "# Rules\n- Write clean code.\n- Follow best practices.\n"
        )
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdTautologicalRule().check(ctx)
        assert len(violations) >= 2

    def test_autofix_removes_tautologies(self, temp_dir):
        content = "# Rules\n- Write clean code.\nRun tests.\n"
        (temp_dir / "AGENTS.md").write_text(content)
        ctx = RepositoryContext(temp_dir)
        rule = AgentsMdTautologicalRule()
        violations = rule.check(ctx)
        fixes = rule.fix(ctx, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "Write clean code" not in fixes[0].fixed_content
        assert "Run tests" in fixes[0].fixed_content

    def test_metadata(self):
        rule = AgentsMdTautologicalRule()
        assert rule.rule_id == "agents-md-tautological"
        assert rule.supports_autofix is True


# ═══════════════════════════════════════════════════════════════════════════════
# 11. agents-md-critical-position
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdCriticalPositionRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdCriticalPositionRule().check(ctx) == []

    def test_critical_at_top_passes(self, temp_dir):
        lines = ["IMPORTANT: Always run tests."] + [f"Line {i}" for i in range(30)]
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdCriticalPositionRule().check(ctx) == []

    def test_critical_at_bottom_passes(self, temp_dir):
        lines = [f"Line {i}" for i in range(30)] + ["MUST always run tests."]
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdCriticalPositionRule().check(ctx) == []

    def test_critical_in_middle_fails(self, temp_dir):
        lines = (
            [f"Line {i}" for i in range(20)]
            + ["NEVER skip tests."]
            + [f"Line {i}" for i in range(20, 40)]
        )
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdCriticalPositionRule().check(ctx)
        assert len(violations) >= 1
        assert (
            "buried" in violations[0].message.lower() or "middle" in violations[0].message.lower()
        )

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nMUST do X.\nNEVER do Y.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdCriticalPositionRule().check(ctx) == []

    def test_has_autofix(self):
        rule = AgentsMdCriticalPositionRule()
        assert rule.supports_autofix is True

    def test_fix_returns_suggest(self, temp_dir):
        lines = (
            [f"Line {i}" for i in range(20)]
            + ["ALWAYS run lint."]
            + [f"Line {i}" for i in range(20, 40)]
        )
        (temp_dir / "AGENTS.md").write_text("\n".join(lines))
        ctx = RepositoryContext(temp_dir)
        rule = AgentsMdCriticalPositionRule()
        violations = rule.check(ctx)
        fixes = rule.fix(ctx, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST

    def test_metadata(self):
        rule = AgentsMdCriticalPositionRule()
        assert rule.rule_id == "agents-md-critical-position"
        assert rule.default_severity() == Severity.INFO


# ═══════════════════════════════════════════════════════════════════════════════
# 12. agents-md-hook-candidate
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentsMdHookCandidateRule:
    def test_no_file_passes(self, temp_dir):
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdHookCandidateRule().check(ctx) == []

    def test_clean_file_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nPrefer descriptive names.\n")
        ctx = RepositoryContext(temp_dir)
        assert AgentsMdHookCandidateRule().check(ctx) == []

    def test_always_run_after_detected(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nAlways run lint after making changes.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdHookCandidateRule().check(ctx)
        assert len(violations) >= 1
        assert "hook" in violations[0].message.lower()

    def test_format_before_commit_detected(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nFormat code before committing.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdHookCandidateRule().check(ctx)
        assert len(violations) >= 1

    def test_never_push_without_tests_detected(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Rules\nNever push without running tests.\n")
        ctx = RepositoryContext(temp_dir)
        violations = AgentsMdHookCandidateRule().check(ctx)
        assert len(violations) >= 1

    def test_metadata(self):
        rule = AgentsMdHookCandidateRule()
        assert rule.rule_id == "agents-md-hook-candidate"
        assert rule.default_severity() == Severity.INFO
        assert rule.supports_autofix is False
