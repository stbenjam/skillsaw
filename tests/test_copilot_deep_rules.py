"""Tests for deep Copilot instruction rules"""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity, AutofixConfidence
from skillsaw.rules.builtin.copilot_instructions import (
    CopilotInstructionsLengthRule,
    CopilotInstructionsLanguageQualityRule,
    CopilotInstructionsActionabilityRule,
    CopilotInstructionsStaleRefsRule,
    CopilotInstructionsDuplicationRule,
    CopilotInstructionsScopeRule,
    CopilotInstructionsFormatRule,
    CopilotInstructionsConflictRule,
    CopilotInstructionsFrontmatterKeysRule,
    CopilotInstructionsExcludeAgentRule,
)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


def _write_copilot_global(temp_dir: Path, content: str):
    github_dir = temp_dir / ".github"
    github_dir.mkdir(exist_ok=True)
    (github_dir / "copilot-instructions.md").write_text(content)


def _write_dot_instructions(temp_dir: Path, content: str, subdir: str = ""):
    if subdir:
        target = temp_dir / subdir
        target.mkdir(parents=True, exist_ok=True)
    else:
        target = temp_dir
    (target / ".instructions.md").write_text(content)


# ===========================================================================
# CopilotInstructionsLengthRule
# ===========================================================================


class TestCopilotInstructionsLengthRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsLengthRule()
        assert rule.rule_id == "copilot-instructions-length"
        assert rule.default_severity() == Severity.WARNING

    def test_short_file_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "# Instructions\nUse TypeScript.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLengthRule().check(context)
        assert len(violations) == 0

    def test_long_file_warns(self, temp_dir):
        lines = ["Line {}\n".format(i) for i in range(250)]
        _write_copilot_global(temp_dir, "".join(lines))
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLengthRule().check(context)
        assert len(violations) == 1
        assert "250 lines" in violations[0].message

    def test_custom_max_lines(self, temp_dir):
        lines = ["Line {}\n".format(i) for i in range(60)]
        _write_copilot_global(temp_dir, "".join(lines))
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsLengthRule(config={"max-lines": 50})
        violations = rule.check(context)
        assert len(violations) == 1

    def test_dot_instructions_also_checked(self, temp_dir):
        lines = ["Line {}\n".format(i) for i in range(250)]
        content = '---\napplyTo: "**/*.py"\n---\n' + "".join(lines)
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLengthRule().check(context)
        assert len(violations) == 1

    def test_no_files_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLengthRule().check(context)
        assert len(violations) == 0


# ===========================================================================
# CopilotInstructionsLanguageQualityRule
# ===========================================================================


class TestCopilotInstructionsLanguageQualityRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsLanguageQualityRule()
        assert rule.rule_id == "copilot-instructions-language-quality"
        assert rule.default_severity() == Severity.INFO

    def test_clean_file_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nUse TypeScript for all files.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLanguageQualityRule().check(context)
        assert len(violations) == 0

    def test_hedging_language_flagged(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nTry to use TypeScript if possible.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLanguageQualityRule().check(context)
        assert len(violations) >= 1
        messages = " ".join(v.message for v in violations)
        assert "try to" in messages.lower() or "if possible" in messages.lower()

    def test_vague_language_flagged(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nHandle errors properly and be careful.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLanguageQualityRule().check(context)
        assert len(violations) >= 1

    def test_line_numbers_reported(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nGood line.\nTry to use hooks.\nAnother line.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsLanguageQualityRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line is not None

    def test_autofix_removes_weak_phrases(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nTry to use TypeScript.\n")
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsLanguageQualityRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) >= 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert "try to" not in fixes[0].fixed_content.lower()


# ===========================================================================
# CopilotInstructionsActionabilityRule
# ===========================================================================


class TestCopilotInstructionsActionabilityRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsActionabilityRule()
        assert rule.rule_id == "copilot-instructions-actionability"
        assert rule.default_severity() == Severity.WARNING

    def test_actionable_instructions_pass(self, temp_dir):
        _write_copilot_global(
            temp_dir,
            "# Rules\nUse 4-space indentation.\nRun pytest before committing.\n",
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsActionabilityRule().check(context)
        assert len(violations) == 0

    def test_tautological_instruction_flagged(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nWrite clean code.\nBe helpful.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsActionabilityRule().check(context)
        assert len(violations) >= 1

    def test_autofix_removes_tautological_lines(self, temp_dir):
        _write_copilot_global(
            temp_dir,
            "# Rules\nUse TypeScript.\nWrite clean code.\nRun tests.\n",
        )
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsActionabilityRule()
        violations = rule.check(context)
        assert len(violations) >= 1
        fixes = rule.fix(context, violations)
        assert len(fixes) >= 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "write clean code" not in fixes[0].fixed_content.lower()
        assert "Use TypeScript" in fixes[0].fixed_content


# ===========================================================================
# CopilotInstructionsStaleRefsRule
# ===========================================================================


class TestCopilotInstructionsStaleRefsRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsStaleRefsRule()
        assert rule.rule_id == "copilot-instructions-stale-refs"
        assert rule.default_severity() == Severity.WARNING

    def test_no_refs_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nUse TypeScript.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsStaleRefsRule().check(context)
        assert len(violations) == 0

    def test_dead_file_ref_flagged(self, temp_dir):
        _write_copilot_global(
            temp_dir,
            "# Rules\nSee `src/config/settings.ts` for defaults.\n",
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsStaleRefsRule().check(context)
        assert len(violations) >= 1
        assert "src/config/settings.ts" in violations[0].message

    def test_existing_file_ref_passes(self, temp_dir):
        src_dir = temp_dir / "src" / "config"
        src_dir.mkdir(parents=True)
        (src_dir / "settings.ts").write_text("export default {}")
        _write_copilot_global(
            temp_dir,
            "# Rules\nSee `src/config/settings.ts` for defaults.\n",
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsStaleRefsRule().check(context)
        assert len(violations) == 0

    def test_line_number_reported(self, temp_dir):
        _write_copilot_global(
            temp_dir,
            "# Rules\nGood line.\nSee `src/missing/file.ts` for info.\n",
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsStaleRefsRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line is not None


# ===========================================================================
# CopilotInstructionsDuplicationRule
# ===========================================================================


class TestCopilotInstructionsDuplicationRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsDuplicationRule()
        assert rule.rule_id == "copilot-instructions-duplication"
        assert rule.default_severity() == Severity.WARNING

    def test_unique_files_pass(self, temp_dir):
        _write_copilot_global(temp_dir, "# Global\nUse TypeScript for all projects.\n")
        content = '---\napplyTo: "**/*.py"\n---\nUse type hints in all Python files.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsDuplicationRule().check(context)
        assert len(violations) == 0

    def test_duplicate_content_flagged(self, temp_dir):
        shared_content = "\n".join(
            [f"Rule {i}: Do something specific for rule {i}." for i in range(20)]
        )
        _write_copilot_global(temp_dir, "# Rules\n" + shared_content + "\n")
        content = '---\napplyTo: "**/*.py"\n---\n# Rules\n' + shared_content + "\n"
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsDuplicationRule().check(context)
        assert len(violations) >= 1
        assert "similar" in violations[0].message.lower()

    def test_single_file_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nUse TypeScript.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsDuplicationRule().check(context)
        assert len(violations) == 0


# ===========================================================================
# CopilotInstructionsScopeRule
# ===========================================================================


class TestCopilotInstructionsScopeRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsScopeRule()
        assert rule.rule_id == "copilot-instructions-scope"
        assert rule.default_severity() == Severity.WARNING

    def test_specific_glob_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\n---\nUse type hints.\n'
        _write_dot_instructions(temp_dir, content)
        # Create a .py file so the glob matches
        (temp_dir / "test.py").write_text("pass")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsScopeRule().check(context)
        assert len(violations) == 0

    def test_broad_glob_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*"\n---\nGeneral instructions.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsScopeRule().check(context)
        assert len(violations) >= 1
        assert "matches all files" in violations[0].message

    def test_star_glob_flagged(self, temp_dir):
        content = '---\napplyTo: "*"\n---\nGeneral instructions.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsScopeRule().check(context)
        assert len(violations) >= 1

    def test_no_match_glob_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.rs"\n---\nUse Rust conventions.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsScopeRule().check(context)
        assert len(violations) >= 1
        assert "matches no files" in violations[0].message

    def test_matching_glob_passes(self, temp_dir):
        (temp_dir / "main.rs").write_text("fn main() {}")
        content = '---\napplyTo: "**/*.rs"\n---\nUse Rust conventions.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsScopeRule().check(context)
        assert len(violations) == 0

    def test_autofix_narrows_broad_glob(self, temp_dir):
        content = '---\napplyTo: "**/*"\n---\nGeneral instructions.\n'
        _write_dot_instructions(temp_dir, content)
        (temp_dir / "app.py").write_text("pass")
        (temp_dir / "test.py").write_text("pass")
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsScopeRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        broad_violation = [v for v in violations if "matches all files" in v.message]
        if broad_violation:
            relevant_fixes = [f for f in fixes if "Narrow" in f.description]
            assert len(relevant_fixes) >= 1
            assert relevant_fixes[0].confidence == AutofixConfidence.SUGGEST


# ===========================================================================
# CopilotInstructionsFormatRule
# ===========================================================================


class TestCopilotInstructionsFormatRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsFormatRule()
        assert rule.rule_id == "copilot-instructions-format"
        assert rule.default_severity() == Severity.WARNING

    def test_well_structured_passes(self, temp_dir):
        _write_copilot_global(
            temp_dir,
            "# Instructions\n\n## Coding Style\nUse TypeScript.\n\n## Testing\nRun jest.\n",
        )
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFormatRule().check(context)
        assert len(violations) == 0

    def test_wall_of_text_flagged(self, temp_dir):
        lines = [f"Rule {i}: do something.\n" for i in range(25)]
        _write_copilot_global(temp_dir, "".join(lines))
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFormatRule().check(context)
        assert len(violations) >= 1
        assert "no markdown headings" in violations[0].message

    def test_short_file_without_headings_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "Use TypeScript.\nRun tests.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFormatRule().check(context)
        assert len(violations) == 0

    def test_empty_body_with_frontmatter_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\n---\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFormatRule().check(context)
        assert len(violations) >= 1
        assert "no content body" in violations[0].message

    def test_autofix_adds_heading(self, temp_dir):
        lines = [f"Rule {i}: do something.\n" for i in range(25)]
        _write_copilot_global(temp_dir, "".join(lines))
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsFormatRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) >= 1
        assert "# Instructions" in fixes[0].fixed_content

    def test_autofix_adds_template_body(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\n---\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsFormatRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) >= 1
        assert "TODO" in fixes[0].fixed_content


# ===========================================================================
# CopilotInstructionsConflictRule
# ===========================================================================


class TestCopilotInstructionsConflictRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsConflictRule()
        assert rule.rule_id == "copilot-instructions-conflict"
        assert rule.default_severity() == Severity.WARNING

    def test_no_conflict_passes(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nAlways use TypeScript.\n")
        content = '---\napplyTo: "**/*.py"\n---\nAlways use type hints.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsConflictRule().check(context)
        assert len(violations) == 0

    def test_conflict_flagged(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nAlways use tabs.\n")
        content = '---\napplyTo: "**/*.py"\n---\nNever use tabs.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsConflictRule().check(context)
        assert len(violations) >= 1
        assert "conflicting" in violations[0].message.lower()

    def test_same_polarity_no_conflict(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nAlways use TypeScript.\n")
        content = '---\napplyTo: "**/*.ts"\n---\nAlways use TypeScript for components.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsConflictRule().check(context)
        assert len(violations) == 0

    def test_single_file_no_conflict(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nAlways use tabs.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsConflictRule().check(context)
        assert len(violations) == 0


# ===========================================================================
# CopilotInstructionsFrontmatterKeysRule
# ===========================================================================


class TestCopilotInstructionsFrontmatterKeysRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsFrontmatterKeysRule()
        assert rule.rule_id == "copilot-instructions-frontmatter-keys"
        assert rule.default_severity() == Severity.WARNING

    def test_valid_keys_pass(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: code-review\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 0

    def test_unknown_key_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\ntitle: My Rules\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 1
        assert "title" in violations[0].message

    def test_multiple_unknown_keys_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\ntitle: Rules\nauthor: me\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 2

    def test_line_number_reported(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\ntitle: Rules\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_autofix_removes_unknown_keys(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\ntitle: Rules\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsFrontmatterKeysRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "title" not in fixes[0].fixed_content
        assert "applyTo" in fixes[0].fixed_content

    def test_no_frontmatter_passes(self, temp_dir):
        _write_dot_instructions(temp_dir, "Just content without frontmatter.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 0

    def test_global_copilot_not_checked(self, temp_dir):
        _write_copilot_global(temp_dir, "# Rules\nUse TypeScript.\n")
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsFrontmatterKeysRule().check(context)
        assert len(violations) == 0


# ===========================================================================
# CopilotInstructionsExcludeAgentRule
# ===========================================================================


class TestCopilotInstructionsExcludeAgentRule:
    def test_rule_metadata(self):
        rule = CopilotInstructionsExcludeAgentRule()
        assert rule.rule_id == "copilot-instructions-exclude-agent"
        assert rule.default_severity() == Severity.ERROR

    def test_valid_code_review_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: code-review\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 0

    def test_valid_cloud_agent_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: cloud-agent\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 0

    def test_invalid_value_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: copilot\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 1
        assert "copilot" in violations[0].message

    def test_invalid_type_flagged(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: 42\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 1
        assert "string or list" in violations[0].message.lower()

    def test_list_of_valid_values_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent:\n  - code-review\n  - cloud-agent\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 0

    def test_list_with_invalid_value_flagged(self, temp_dir):
        content = (
            '---\napplyTo: "**/*.py"\nexcludeAgent:\n  - code-review\n  - invalid\n---\nContent.\n'
        )
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 1
        assert "invalid" in violations[0].message

    def test_no_exclude_agent_passes(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 0

    def test_autofix_corrects_common_mistake(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: code_review\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsExcludeAgentRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "code-review" in fixes[0].fixed_content

    def test_autofix_corrects_cloud_agent_mistake(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: cloud_agent\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        rule = CopilotInstructionsExcludeAgentRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "cloud-agent" in fixes[0].fixed_content

    def test_line_number_reported(self, temp_dir):
        content = '---\napplyTo: "**/*.py"\nexcludeAgent: wrong\n---\nContent.\n'
        _write_dot_instructions(temp_dir, content)
        context = RepositoryContext(temp_dir)
        violations = CopilotInstructionsExcludeAgentRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3
