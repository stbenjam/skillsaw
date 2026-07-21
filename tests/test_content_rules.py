"""Tests for content intelligence rules."""

import json
import os
import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import AutofixConfidence, Severity
from skillsaw.rules.builtin.content_rules import (
    ContentWeakLanguageRule,
    ContentTautologicalRule,
    ContentCriticalPositionRule,
    ContentRedundantWithToolingRule,
    ContentInstructionBudgetRule,
    ContentNegativeOnlyRule,
    ContentSectionLengthRule,
    ContentContradictionRule,
    ContentHookCandidateRule,
    ContentActionabilityScoreRule,
    ContentCognitiveChunksRule,
    ContentEmbeddedSecretsRule,
    ContentBannedReferencesRule,
    ContentInconsistentTerminologyRule,
    ContentInstructionDriftRule,
    ContentBrokenInternalReferenceRule,
    ContentUnlinkedInternalReferenceRule,
    ContentPlaceholderTextRule,
)
from skillsaw.rules.builtin.content import (
    ContentUnclosedFenceRule,
    ContentRepeatedDirectiveRule,
    ContentEmphasisDensityRule,
    ContentMissingStopConditionRule,
)

# Stripe test keys built from parts to avoid triggering GitHub push protection
_STRIPE_SK = "sk" + "_live_" + "TESTFAKEKEYDONOTUSE00000"
_STRIPE_RK = "rk" + "_live_" + "TESTFAKEKEYDONOTUSE00000"


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def copy_content_fixture(name, dest):
    """Copy ``tests/fixtures/content/<name>`` into *dest*, return the repo root."""
    src = _FIXTURES_DIR / "content" / name
    dst = dest / name
    shutil.copytree(src, dst)
    return dst


class TestContentWeakLanguageRule:
    def test_rule_metadata(self):
        rule = ContentWeakLanguageRule()
        assert rule.rule_id == "content-weak-language"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_weak_language(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) >= 3

    def test_clean_instructions_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation.\nReturn 404 for missing resources.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) == 0

    def test_code_blocks_not_scanned(self, temp_dir):
        content = "# Rules\n```\nTry to handle errors gracefully if possible.\n```\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) == 0

    def test_consider_example_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Consider this example:\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) == 0

    def test_consider_using_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Consider using TypeScript for type safety.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) >= 1

    def test_new_hedging_patterns(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("You might want to add error handling.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) >= 1

    def test_reference_files_get_info_severity(self, temp_dir):
        """skill-ref content blocks should get INFO severity instead of WARNING."""
        # Set up a skill repo with a references directory
        (temp_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\nHello\n"
        )
        refs_dir = temp_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("Handle errors properly and correctly.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        # Should have violations from the reference file
        ref_violations = [v for v in violations if "references" in str(v.file_path)]
        assert len(ref_violations) >= 1
        # All reference file violations should be INFO severity
        for v in ref_violations:
            assert v.severity == Severity.INFO

    def test_non_reference_files_keep_warning_severity(self, temp_dir):
        """Non-reference content blocks should keep WARNING severity."""
        (temp_dir / "CLAUDE.md").write_text("Handle errors properly and correctly.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        assert len(violations) >= 1
        for v in violations:
            assert v.severity == Severity.WARNING


class TestContentTautologicalRule:
    def test_rule_metadata(self):
        rule = ContentTautologicalRule()
        assert rule.rule_id == "content-tautological"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_tautology(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Always write clean code.\nFollow best practices.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentTautologicalRule().check(context)
        assert len(violations) >= 2

    def test_specific_instructions_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation for Python.\nReturn early on error.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentTautologicalRule().check(context)
        assert len(violations) == 0


class TestContentCriticalPositionRule:
    def test_rule_metadata(self):
        rule = ContentCriticalPositionRule()
        assert rule.rule_id == "content-critical-position"
        assert rule.default_severity() == Severity.WARNING

    def test_critical_in_middle_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "IMPORTANT: Never skip tests."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCriticalPositionRule().check(context)
        assert len(violations) >= 1
        assert "dead zone" in violations[0].message.lower()

    def test_critical_at_top_passes(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[2] = "IMPORTANT: Never skip tests."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCriticalPositionRule().check(context)
        assert len(violations) == 0

    def test_short_file_no_violations(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("MUST do this.\nNEVER do that.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCriticalPositionRule().check(context)
        assert len(violations) == 0

    def test_lowercase_keywords_not_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "This function must return a value."
        lines[26] = "The required fields are: name, email."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCriticalPositionRule().check(context)
        assert len(violations) == 0


class TestContentRedundantWithToolingRule:
    def test_rule_metadata(self):
        rule = ContentRedundantWithToolingRule()
        assert rule.rule_id == "content-redundant-with-tooling"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_editorconfig_redundancy(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_size = 4\n")
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentRedundantWithToolingRule().check(context)
        assert len(violations) >= 1
        assert ".editorconfig" in violations[0].message

    def test_no_config_files_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentRedundantWithToolingRule().check(context)
        assert len(violations) == 0


class TestContentInstructionBudgetRule:
    def test_rule_metadata(self):
        rule = ContentInstructionBudgetRule()
        assert rule.rule_id == "content-instruction-budget"
        assert rule.default_severity() == Severity.WARNING

    def test_over_budget_warns(self, temp_dir):
        lines = [f"- Use tool_{i}" for i in range(130)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInstructionBudgetRule().check(context)
        assert len(violations) >= 1

    def test_under_budget_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\nSome description.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInstructionBudgetRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentInstructionBudgetRule().check(context)
        assert len(violations) == 0


class TestContentNegativeOnlyRule:
    def test_rule_metadata(self):
        rule = ContentNegativeOnlyRule()
        assert rule.rule_id == "content-negative-only"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_negative_without_alternative(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Never use var in JavaScript.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 1

    def test_negative_with_alternative_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Don't use var. Use const or let instead.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_always_alternative_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            '**Never use "good" or "bad" alone - always explain what they mean in context.**\n'
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_no_negatives_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use const for all declarations.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_backtick_use_alternative_passes(self, temp_dir):
        """'use `/payload-aggregate`' should count as a positive alternative."""
        (temp_dir / "CLAUDE.md").write_text(
            "Do NOT use the aggregated job name with `/payload-job` — "
            "you must use `/payload-aggregate` with the underlying job name\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_bold_use_alternative_passes(self, temp_dir):
        """'Use **PatternFly 6 variables**' should count as positive."""
        (temp_dir / "CLAUDE.md").write_text(
            "Use **PatternFly 6 token variables only**. " "NEVER use hex colors or old format.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_heading_with_dont_skipped(self, temp_dir):
        """Markdown headings like '### Don't Do This' should be skipped."""
        (temp_dir / "CLAUDE.md").write_text(
            "### Insecure Approach (Don't Do This)\n" "```bash\ncurl -u user:pass ...\n```\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_follow_alternative_passes(self, temp_dir):
        """'Do not use X - follow Y' should count as having an alternative."""
        (temp_dir / "CLAUDE.md").write_text(
            "Do not use generic testing advice - follow the project-specific guidelines.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_positive_before_on_same_line_passes(self, temp_dir):
        """Positive verb before the negative on the same line should count."""
        (temp_dir / "CLAUDE.md").write_text(
            "Summarize which jobs are failing. " "Do NOT use 'Revert ...' as the summary.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_generate_alternative_passes(self, temp_dir):
        """'Generate a short sentence; do not use more than one' has positive."""
        (temp_dir / "CLAUDE.md").write_text(
            "Generate a single short sentence summarizing the failure. "
            "Do not use more than one sentence.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_negative_with_add_alternative_passes(self, temp_dir):
        """'Add X. Do not use Y' should count as having an alternative."""
        (temp_dir / "CLAUDE.md").write_text(
            'Add `console.navigation/section` with id "plugins". ' 'Do not use section "home".\n'
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_scope_boundary_dont_use_when_skipped(self, temp_dir):
        """'Don't use this when:' is a scope boundary, not a prohibition."""
        (temp_dir / "CLAUDE.md").write_text(
            "Don't use this when:\n" "- The file is auto-generated\n" "- The output is temporary\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_scope_boundary_dont_use_when_with_star(self, temp_dir):
        """'Don't use this when*' (star variant) is also a scope boundary."""
        (temp_dir / "CLAUDE.md").write_text(
            "Don't use this skill when*\n" "- The input is invalid\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_scope_boundary_do_not_use_when_skipped(self, temp_dir):
        """'Do not use X when:' without apostrophe should also be skipped."""
        (temp_dir / "CLAUDE.md").write_text(
            "Do not use this tool when:\n" "- There's no internet connection\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 0

    def test_plain_dont_use_still_flagged(self, temp_dir):
        """Plain 'Don't use X' without 'when:' should still be flagged."""
        (temp_dir / "CLAUDE.md").write_text("Don't use eval in production code.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentNegativeOnlyRule().check(context)
        assert len(violations) == 1


class TestContentSectionLengthRule:
    def test_rule_metadata(self):
        rule = ContentSectionLengthRule()
        assert rule.rule_id == "content-section-length"
        assert rule.default_severity() == Severity.INFO

    def test_long_section_warned(self, temp_dir):
        lines = ["# Long Section"] + [
            f"Configure the application setting number {i} to the recommended production value for optimal performance."
            for i in range(60)
        ]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentSectionLengthRule().check(context)
        assert len(violations) >= 1
        assert "tokens" in violations[0].message

    def test_short_sections_pass(self, temp_dir):
        content = "# Section 1\nLine 1\nLine 2\n\n# Section 2\nLine 3\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentSectionLengthRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentSectionLengthRule().check(context)
        assert len(violations) == 0

    def test_top_of_file_section_reports_line_1(self, temp_dir):
        """Top-of-file sections must report line=1, not None (regression)."""
        content = "\n".join(
            [f"Long instruction number {i} for top of file section." for i in range(200)]
        )
        (temp_dir / "CLAUDE.md").write_text(content + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentSectionLengthRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line == 1


class TestContentContradictionRule:
    def test_rule_metadata(self):
        rule = ContentContradictionRule()
        assert rule.rule_id == "content-contradiction"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_contradiction(self, temp_dir):
        content = "# Instructions\nMove fast and break things.\nAlways write comprehensive tests.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) >= 1
        assert "contradiction" in violations[0].message.lower()

    def test_no_contradiction_passes(self, temp_dir):
        content = "# Instructions\nUse 4-space indentation.\nRun tests before committing.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) == 0

    def test_keep_simple_handle_edge_cases(self, temp_dir):
        content = "Keep it simple.\nHandle all edge cases.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) >= 1

    def test_negation_prefix_non_exhaustive(self, temp_dir):
        """non-exhaustive should not match as exhaustive (issue #148)"""
        content = "Provide a minimal, non-exhaustive overview.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) == 0

    def test_negation_prefix_not_exhaustive(self, temp_dir):
        """'not exhaustive' should not match as exhaustive"""
        content = "The list is minimal and not exhaustive.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) == 0

    def test_real_contradiction_still_detected(self, temp_dir):
        """Real contradictions (without negation) are still detected"""
        content = "Be minimal in your approach.\nProvide exhaustive documentation.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) >= 1

    def test_mixed_negated_and_non_negated_still_flags(self, temp_dir):
        """A negated occurrence should not suppress a real non-negated one"""
        content = (
            "Provide a minimal, non-exhaustive overview first.\n"
            "Also include exhaustive implementation notes.\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentContradictionRule().check(context)
        assert len(violations) >= 1


class TestContentHookCandidateRule:
    def test_rule_metadata(self):
        rule = ContentHookCandidateRule()
        assert rule.rule_id == "content-hook-candidate"
        assert rule.default_severity() == Severity.INFO

    def test_detects_format_before_commit(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Format code before committing.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentHookCandidateRule().check(context)
        assert len(violations) >= 1
        assert "hook" in violations[0].message.lower()

    def test_detects_run_tests_before_commit(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Run tests before every commit.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentHookCandidateRule().check(context)
        assert len(violations) >= 1

    def test_non_hook_instructions_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use descriptive commit messages.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentHookCandidateRule().check(context)
        assert len(violations) == 0


class TestContentActionabilityScoreRule:
    def test_rule_metadata(self):
        rule = ContentActionabilityScoreRule()
        assert rule.rule_id == "content-actionability-score"
        assert rule.default_severity() == Severity.INFO

    def test_low_actionability_warned(self, temp_dir):
        lines = [f"This is a description about something {i}." for i in range(20)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentActionabilityScoreRule().check(context)
        assert len(violations) >= 1
        assert "actionability" in violations[0].message.lower()

    def test_high_actionability_passes(self, temp_dir):
        content = "- Use 4-space indentation\n- Run `npm test` before commits\n- Check `src/config.ts` settings\n- Add error handling for API calls\n- Follow the `eslint` rules\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentActionabilityScoreRule().check(context)
        assert len(violations) == 0

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Short.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentActionabilityScoreRule().check(context)
        assert len(violations) == 0


class TestContentCognitiveChunksRule:
    def test_rule_metadata(self):
        rule = ContentCognitiveChunksRule()
        assert rule.rule_id == "content-cognitive-chunks"
        assert rule.default_severity() == Severity.INFO

    def test_no_headings_warned(self, temp_dir):
        lines = [f"Instruction {i}." for i in range(20)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCognitiveChunksRule().check(context)
        assert len(violations) >= 1
        assert "heading" in violations[0].message.lower()

    def test_single_heading_warned(self, temp_dir):
        lines = ["# Everything"] + [f"Instruction {i}." for i in range(40)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCognitiveChunksRule().check(context)
        assert len(violations) >= 1
        assert "single heading" in violations[0].message.lower()

    def test_well_organized_passes(self, temp_dir):
        content = "# Section 1\nDo X.\n\n# Section 2\nDo Y.\n\n# Section 3\nDo Z.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentCognitiveChunksRule().check(context)
        assert len(violations) == 0

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Short.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentCognitiveChunksRule().check(context)
        assert len(violations) == 0

    def test_hooks_json_skipped(self, temp_dir):
        """hooks.json should not trigger cognitive-chunks (structured data, not markdown)"""
        plugin_dir = temp_dir / "hooks"
        plugin_dir.mkdir(parents=True)
        hooks_content = {
            "description": "Auto-format Go files with gofmt after write/edit",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [
                            {
                                "type": "command",
                                "if": "Write(**/*.go)",
                                "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gofmt.sh",
                                "timeout": 10,
                            }
                        ],
                    },
                    {
                        "matcher": "Edit",
                        "hooks": [
                            {
                                "type": "command",
                                "if": "Edit(**/*.go)",
                                "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gofmt.sh",
                                "timeout": 10,
                            }
                        ],
                    },
                ]
            },
        }
        (plugin_dir / "hooks.json").write_text(json.dumps(hooks_content, indent=2))
        # Also add a plugin.json so the tree builder recognizes this as a plugin
        (temp_dir / "plugin.json").write_text(
            json.dumps({"name": "test-plugin", "description": "Test"})
        )
        context = RepositoryContext(temp_dir)
        violations = ContentCognitiveChunksRule().check(context)
        assert len(violations) == 0


class TestContentEmbeddedSecretsRule:
    def test_rule_metadata(self):
        rule = ContentEmbeddedSecretsRule()
        assert rule.rule_id == "content-embedded-secrets"
        assert rule.default_severity() == Severity.ERROR

    def test_detects_openai_key(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Set API key: sk-abcdefghijklmnopqrstuvwxyz1234\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert "API key" in violations[0].message

    def test_detects_github_token(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use token ghp_abcdefghijklmnopqrstuvwxyz123456789012\n"  # notsecret
        )
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1

    def test_detects_aws_key(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("AWS key: AKIAIOSFODNN7EXAMPLE\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1

    def test_clean_file_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use environment variables for API keys.\nNever hardcode secrets.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) == 0

    def test_reports_line_number(self, temp_dir):
        content = "Line 1\nLine 2\nPassword: password='xK9$mQ2vLp8#nR4zW7@j'\nLine 4\n"  # notsecret
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line == 3

    @pytest.mark.parametrize(
        "secret,expected_desc",
        [
            ("sk-ant-api03-abcdefghijklmnopqrst", "Anthropic API key"),
            ("ghr_abcdefghijklmnopqrstuvwxyz123456789012", "GitHub refresh token"),  # notsecret
            ("ASIAIOSFODNN7EXAMPLE", "AWS temporary access key"),
            ("xoxa-123456789012-abcdefghij", "Slack app token"),
            ("xoxr-123456789012-abcdefghij", "Slack refresh token"),
            (_STRIPE_SK, "Stripe secret key"),
            (_STRIPE_RK, "Stripe restricted key"),
            ("AIzaSyATESTFAKEKEYDONOTUSE0000000000000", "Google API key"),  # notsecret
            ("SK00000000000000000000000000000000", "Twilio API key"),  # notsecret
            (
                "SG.abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyz0123456789abcdefghijk",  # notsecret
                "SendGrid API key",
            ),
            ("npm_abcdefghijklmnopqrstuvwxyz1234567890", "npm access token"),  # notsecret
            ("pypi-abcdefghijklmnopqrstuvwxyz", "PyPI API token"),
            (
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456",
                "JSON Web Token",
            ),
            ("-----BEGIN RSA PRIVATE KEY-----", "Private key"),
            ("-----BEGIN OPENSSH PRIVATE KEY-----", "Private key"),
            ("secret_key = 'abcdefghijklmnopqrstuvwxyz'", "Hardcoded secret key"),
            ("access_token = 'abcdefghijklmnopqrstuvwxyz'", "Hardcoded access token"),
        ],
        ids=[
            "anthropic",
            "github-refresh",
            "aws-temp",
            "slack-app",
            "slack-refresh",
            "stripe-secret",
            "stripe-restricted",
            "google",
            "twilio",
            "sendgrid",
            "npm",
            "pypi",
            "jwt",
            "rsa-private-key",
            "openssh-private-key",
            "generic-secret-key",
            "generic-access-token",
        ],
    )
    def test_detects_secret_pattern(self, temp_dir, secret, expected_desc):
        (temp_dir / "CLAUDE.md").write_text(f"Config: {secret}\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert expected_desc in violations[0].message

    def test_no_false_positive_on_env_var_reference(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Set api_key = $OPENAI_API_KEY from environment.\n"
            "Use `export STRIPE_KEY=...` to configure.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) == 0

    def test_no_false_positive_on_short_placeholder(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use sk-YOUR_KEY as the token.\n" "Set password = 'short'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) == 0

    @pytest.mark.parametrize(
        "line",
        [
            'password="hunter2placeholder"',
            "password = 'your-password-here'",
            'password: "aaaaaaaaaaaaaaaa"',
            'password = "dummy-value-123"',  # notsecret
            'api_key = "<your-api-key-goes-here>"',
            'api_key = "${MY_API_KEY_FROM_ENV}"',
            'api_key = "EXAMPLE_KEY_1234567890"',
            'api_key = "abababababababab"',
            'secret_key = "{{ secrets.PRODUCTION_KEY }}"',
            'access_token = "insert-real-value-here"',
            'password = "$DB_PASSWORD"',
            'password = "helloworld"',
            # "password"/"token" inside the value: gitleaks-stopword parity;
            # these exact shapes appear as placeholders in real skill repos
            # (auth0/agent-skills) and pass the entropy gate.
            'password = "securePassword123"',
            'access_token = "my-oauth-token-12345"',
        ],
        ids=[
            "hunter2",
            "your-word",
            "all-same-char",
            "dummy-word",
            "angle-bracket-template",
            "shell-template-var",
            "example-word",
            "low-entropy",
            "jinja-template",
            "insert-word",
            "bare-env-var",
            "english-short",
            "password-word-realworld",
            "token-word",
        ],
    )
    def test_no_false_positive_on_placeholder_values(self, temp_dir, line):
        """Generic credential assignments with obvious placeholder or
        low-entropy values are documentation examples, not leaks (issue #322)."""
        (temp_dir / "CLAUDE.md").write_text(f"Configure it like this: {line}\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) == 0

    @pytest.mark.parametrize(
        "line,expected_desc",
        [
            ('password = "xK9$mQ2vLp8#nR4z"', "Hardcoded password"),  # notsecret
            ('api_key = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"', "Hardcoded API key"),  # notsecret
            ('secret_key = "kJ8vQz3mN9pL2wXyRb5cDf7g"', "Hardcoded secret key"),  # notsecret
        ],
        ids=["random-password", "hex-api-key", "mixed-secret-key"],
    )
    def test_high_entropy_generic_values_still_fire(self, temp_dir, line, expected_desc):
        (temp_dir / "CLAUDE.md").write_text(f"Config: {line}\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert expected_desc in violations[0].message

    @pytest.mark.parametrize(
        "line",
        [
            # Shannon per-char entropy of an n-char string is capped at
            # log2(n) — a raw 3.5 threshold silently exempts every 8-11 char
            # password.  Length normalization must keep these reportable.
            'password = "k9x2m4qp"',
            'password = "xK9#mQ2$vL"',
            'password = "Tr0ub4dor&3"',
            # $ followed by uppercase inside a random value is not an
            # env-var reference and must not suppress the finding.
            'password = "xK9$MQ2vLp8#nR4z"',  # notsecret
            # Incidental <..> punctuation inside a random value is not an
            # angle-bracket placeholder.
            'password = "k<9x>Km2#pQzW4vT"',  # notsecret
        ],
        ids=[
            "short-random-8",
            "short-random-10",
            "short-random-11",
            "dollar-upper-inside",
            "angle-punct-inside",
        ],
    )
    def test_realistic_secrets_not_suppressed_by_gating(self, temp_dir, line):
        """False-negative regressions: real-shaped secrets must fire despite
        the placeholder/entropy gates."""
        (temp_dir / "CLAUDE.md").write_text(f"Config: {line}\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert "Hardcoded password" in violations[0].message

    @pytest.mark.parametrize(
        "line,expected_desc",
        [
            # "secret" and "passwd" are not in gitleaks/detect-secrets
            # stoplists and plausibly occur inside real credential values —
            # they must not act as placeholder markers.
            ('api_key = "app-secret-x8K2mQ9zL4vN"', "Hardcoded API key"),
            ('password = "xK2passwd9QmZ4vN"', "Hardcoded password"),  # notsecret
        ],
        ids=["secret-substring", "passwd-substring"],
    )
    def test_credential_noun_substrings_not_suppressed(self, temp_dir, line, expected_desc):
        """False-negative regressions: high-entropy values containing
        'secret'/'passwd' are real-secret-shaped, not placeholders."""
        (temp_dir / "CLAUDE.md").write_text(f"Config: {line}\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert expected_desc in violations[0].message

    def test_structured_tokens_not_entropy_gated(self, temp_dir):
        """High-confidence token formats fire even for low-entropy bodies."""
        (temp_dir / "CLAUDE.md").write_text("Use token ghp_" + "a" * 40 + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert "GitHub personal access token" in violations[0].message

    def test_entropy_threshold_configurable(self, temp_dir):
        # Distinct repo dirs: the utils read cache is keyed by path, so
        # rewriting the same file within a test would read stale content.
        repo_raise = temp_dir / "raise"
        repo_lower = temp_dir / "lower"
        repo_raise.mkdir()
        repo_lower.mkdir()
        (repo_raise / "CLAUDE.md").write_text(
            'Config: api_key = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"\n'  # notsecret
        )
        # Raising the threshold above the value's entropy suppresses it
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": 5.0})
        assert rule.check(RepositoryContext(repo_raise)) == []
        # Lowering it lets low-entropy values through
        (repo_lower / "CLAUDE.md").write_text('Config: api_key = "abababababababab"\n')
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": 0.5})
        assert len(rule.check(RepositoryContext(repo_lower))) == 1

    def test_entropy_threshold_invalid_config_uses_default(self, temp_dir):
        """An unparseable threshold falls back to the 3.5 default: values on
        either side of the default must behave exactly as with no config
        (marker-free values, so the entropy gate alone decides)."""
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": "nonsense"})
        # Distinct repo dirs: the utils read cache is keyed by path, so
        # rewriting the same file within a test would read stale content.
        repo_low = temp_dir / "low"
        repo_high = temp_dir / "high"
        repo_low.mkdir()
        repo_high.mkdir()
        # Below the default threshold (1.0 bits/char): suppressed.
        (repo_low / "CLAUDE.md").write_text('Config: api_key = "abababababababab"\n')
        assert rule.check(RepositoryContext(repo_low)) == []
        # Above it (hex, ~4.0 bits/char): still fires.
        (repo_high / "CLAUDE.md").write_text(
            'Config: api_key = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"\n'  # notsecret
        )
        assert len(rule.check(RepositoryContext(repo_high))) == 1

    def test_additional_placeholders_configurable(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            'Config: api_key = "staging-key-9f8a7b6c5d4e3f2a"\n'  # notsecret
        )
        context = RepositoryContext(temp_dir)
        # Fires by default (high entropy, no builtin placeholder marker)
        assert len(ContentEmbeddedSecretsRule().check(context)) == 1
        # Suppressed once the marker is allowlisted
        rule = ContentEmbeddedSecretsRule({"additional-placeholders": ["staging-key"]})
        assert rule.check(context) == []

    def test_no_false_positive_on_placeholder_in_frontmatter(self, temp_dir):
        skill = temp_dir / "skills" / "demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: demo\n"
            'description: Set password = "your-password-here" before running\n'
            "---\n\n# Demo\n\nA demo skill.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) == 0


class TestContentBannedReferencesRule:
    def test_rule_metadata(self):
        rule = ContentBannedReferencesRule()
        assert rule.rule_id == "content-banned-references"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_deprecated_model(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use claude-2 for summarization.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBannedReferencesRule().check(context)
        assert len(violations) >= 1

    def test_detects_old_gpt(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use gpt-3.5 for classification.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBannedReferencesRule().check(context)
        assert len(violations) >= 1

    def test_current_model_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use claude-sonnet-4 for summarization.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBannedReferencesRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentBannedReferencesRule().check(context)
        assert len(violations) == 0

    def test_custom_banned_pattern_fires(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Please use the forbidden-term here.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBannedReferencesRule(
            {"banned": [{"pattern": "forbidden-term", "message": "no forbidden terms"}]}
        )
        violations = rule.check(context)
        assert any("no forbidden terms" in v.message for v in violations)

    def test_literal_less_pattern_still_fires(self, temp_dir):
        """A banned pattern with no extractable literal must not be silently
        skipped by the prefilter (issue #316 secondary claim)."""
        (temp_dir / "CLAUDE.md").write_text("Release date 2024-01-15 is hardcoded.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBannedReferencesRule(
            {
                "skip-builtins": True,
                "banned": [{"pattern": r"\d{4}-\d{2}-\d{2}", "message": "no dates"}],
            }
        )
        violations = rule.check(context)
        assert any("no dates" in v.message for v in violations)

    def test_catastrophic_pattern_times_out_instead_of_hanging(self, temp_dir):
        """A config-supplied ReDoS pattern must be bounded, not hang lint
        (issue #316). A tiny budget keeps the test fast."""
        import time

        body = "evilprefix" + "a" * 40 + "!\n"
        (temp_dir / "CLAUDE.md").write_text(body)
        context = RepositoryContext(temp_dir)
        rule = ContentBannedReferencesRule(
            {
                "skip-builtins": True,
                "regex-timeout": 0.3,
                "banned": [{"pattern": "evilprefix(a+)+$", "message": "boom"}],
            }
        )
        start = time.perf_counter()
        violations = rule.check(context)
        elapsed = time.perf_counter() - start
        # Bounded well under a naive run (which measures tens of seconds).
        assert elapsed < 5.0
        assert any("Skipped banned pattern" in v.message for v in violations)

    def test_timeout_is_clamped_and_zero_disables(self, temp_dir):
        rule = ContentBannedReferencesRule({"regex-timeout": 999})
        assert rule._regex_timeout() == 10.0
        rule = ContentBannedReferencesRule({"regex-timeout": 0})
        assert rule._regex_timeout() == 0.0
        rule = ContentBannedReferencesRule({"regex-timeout": "nonsense"})
        assert rule._regex_timeout() == 2.0


class TestContentInconsistentTerminologyRule:
    def test_rule_metadata(self):
        rule = ContentInconsistentTerminologyRule()
        assert rule.rule_id == "content-inconsistent-terminology"
        assert rule.default_severity() == Severity.INFO

    def test_detects_mixed_terms(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Create a directory for configs.\n")
        (temp_dir / "AGENTS.md").write_text("Create a folder for configs.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert len(violations) >= 1
        assert "directory/folder" in violations[0].message

    def test_consistent_terms_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Create a directory for configs.\n")
        (temp_dir / "AGENTS.md").write_text("Use the directory for output.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert len(violations) == 0

    def test_single_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Create a directory for configs.\nCreate a folder for output.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert len(violations) == 0

    def test_disabled_group_is_skipped(self, temp_dir):
        """Issue #366: a group set to 'off' stops firing while others keep working."""
        (temp_dir / "CLAUDE.md").write_text(
            "The first function parameter is the context directory.\n"
        )
        (temp_dir / "AGENTS.md").write_text("Call the service method in this folder.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentInconsistentTerminologyRule({"groups": {"function/method": "off"}})
        violations = rule.check(context)
        assert violations, "directory/folder group should still fire"
        assert all("function/method" not in v.message for v in violations)
        assert any("directory/folder" in v.message for v in violations)

    @pytest.mark.parametrize("setting", [False, "false", "OFF"])
    def test_disabled_group_accepts_off_spellings(self, temp_dir, setting):
        """YAML 1.1 loaders parse a bare ``off`` as boolean False; quoted
        strings and casing variants must behave the same."""
        (temp_dir / "CLAUDE.md").write_text("Write a helper function.\n")
        (temp_dir / "AGENTS.md").write_text("Write a helper method.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentInconsistentTerminologyRule({"groups": {"function/method": setting}})
        assert rule.check(context) == []

    def test_group_severity_is_case_insensitive(self):
        rule = ContentInconsistentTerminologyRule({"groups": {"function/method": "Warning"}})
        assert rule._group_overrides["function/method"] == Severity.WARNING

    def test_group_severity_override(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Write a helper function in a directory.\n")
        (temp_dir / "AGENTS.md").write_text("Write a helper method in a folder.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentInconsistentTerminologyRule(
            {"severity": "error", "groups": {"function/method": "info"}}
        )
        violations = rule.check(context)
        by_group = {}
        for v in violations:
            group = v.message.split("Inconsistent terminology: ")[1].split(" —")[0]
            by_group[group] = v.severity
        assert by_group["function/method"] == Severity.INFO
        assert by_group["directory/folder"] == Severity.ERROR

    def test_unknown_group_name_rejected(self):
        with pytest.raises(ValueError, match="Unknown terminology group 'bogus'"):
            ContentInconsistentTerminologyRule({"groups": {"bogus": "off"}})

    def test_invalid_group_setting_rejected(self):
        with pytest.raises(ValueError, match="Invalid setting 'loud'"):
            ContentInconsistentTerminologyRule({"groups": {"function/method": "loud"}})

    @pytest.mark.parametrize("bad", [["function/method"], [], "", 0, False])
    def test_groups_must_be_mapping(self, bad):
        with pytest.raises(ValueError, match="must be a mapping"):
            ContentInconsistentTerminologyRule({"groups": bad})

    def test_groups_null_treated_as_absent(self, temp_dir):
        """``groups:`` with no value parses as None and must not raise."""
        (temp_dir / "CLAUDE.md").write_text("Write a helper function.\n")
        (temp_dir / "AGENTS.md").write_text("Write a helper method.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentInconsistentTerminologyRule({"groups": None})
        assert rule._group_overrides == {}
        assert rule.check(context)

    def test_heading_not_counted_as_prose_usage(self, temp_dir):
        """Regression for issue #427: a spelled-out heading shouldn't clash
        with a body that consistently uses the abbreviation elsewhere."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Create Pull Request\n\n"
            "Open a PR against main. Wait for review on the PR before merging.\n"
        )
        (temp_dir / "AGENTS.md").write_text(
            "# Notes\n\nAlways open a PR before merging any change.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert not any("PR/pull request/merge request" in v.message for v in violations)

    def test_code_span_path_not_counted(self, temp_dir):
        """Regression for issue #427: a path segment inside a code span
        shouldn't read as a standalone terminology choice."""
        (temp_dir / "CLAUDE.md").write_text(
            "Use the repo for context. See `.planning/codebase/CONVENTIONS.md` for details.\n"
        )
        (temp_dir / "AGENTS.md").write_text(
            "Clone the repo and read the repo's contributing guide.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert not any("repo/repository/codebase" in v.message for v in violations)

    def test_violation_reports_matching_line(self, temp_dir):
        """Regression for issue #427: violations must point at the specific
        line that used the minority term, not just the file."""
        (temp_dir / "CLAUDE.md").write_text("# Layout\n\nCreate a directory for configs.\n")
        (temp_dir / "AGENTS.md").write_text("# Layout\n\nCreate a folder for output.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        assert violations
        v = violations[0]
        assert v.line == 3
        assert v.file_line == 3

    def test_multiple_coderabbit_fragments_scanned_independently(self, temp_dir):
        """A ``.coderabbit.yaml`` with several instruction fragments produces
        several ``ContentBlock``s that all share the same file path. A
        path-keyed body cache would collapse them onto one fragment's text —
        this must scan (and attribute violations to) each fragment on its
        own terms."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"
            "  instructions: |\n"
            "    Create a new directory for generated assets before running codegen.\n"
            "  tools:\n"
            "    eslint:\n"
            "      instructions: |\n"
            "        Put the eslint config in the project folder root.\n"
        )
        (temp_dir / "CLAUDE.md").write_text("# Notes\n\nKeep the directory layout tidy.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        by_group = [v for v in violations if "directory/folder" in v.message]
        assert len(by_group) == 1
        assert by_group[0].file_path.name == ".coderabbit.yaml"
        assert by_group[0].file_line == 7

    def test_multiple_promptfoo_prompts_scanned_independently(self, temp_dir):
        """Same collapsing risk as coderabbit fragments, for promptfoo's
        multiple ``prompts[i]`` blocks sharing one file path."""
        (temp_dir / "promptfooconfig.yaml").write_text(
            "prompts:\n"
            '  - "Create a new directory for the generated report."\n'
            '  - "Save the output in the results folder."\n'
            "providers:\n"
            "  - openai:gpt-4o-mini\n"
            "tests:\n"
            "  - vars: {}\n"
        )
        (temp_dir / "CLAUDE.md").write_text("# Notes\n\nKeep the directory layout tidy.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentInconsistentTerminologyRule().check(context)
        by_group = [v for v in violations if "directory/folder" in v.message]
        assert len(by_group) == 1
        assert by_group[0].file_path.name == "promptfooconfig.yaml"
        assert by_group[0].file_line == 3


# A realistic ~50-word section shared between instruction files in the
# drift tests below.
_DRIFT_SECTION = """## Testing workflow

Run the full test suite with `make test` before every push. Integration
tests require Docker; start the daemon with `make docker-up` first and
tear it down with `make docker-down` when finished. If a test is flaky,
quarantine it with the flaky marker and file an issue including the
failure output and a link to the CI run.
"""

# The same section after someone edited one copy: an extra closing
# sentence pushes similarity to roughly 0.85 — drifted, not rewritten.
_DRIFT_SECTION_EDITED = (
    _DRIFT_SECTION
    + "Never merge a pull request while the suite is red, even for changes "
    + "that look completely unrelated to the failing test.\n"
)

_DRIFT_PREAMBLE = """# Project guide

General development notes for agents working in this repository.

"""


class TestContentInstructionDriftRule:
    def test_rule_metadata(self):
        rule = ContentInstructionDriftRule()
        assert rule.rule_id == "content-instruction-drift"
        assert rule.default_severity() == Severity.INFO

    def test_detects_drifted_sections(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        claude_content = _DRIFT_PREAMBLE + _DRIFT_SECTION_EDITED
        (temp_dir / "CLAUDE.md").write_text(claude_content)
        context = RepositoryContext(temp_dir)
        violations = ContentInstructionDriftRule().check(context)
        assert len(violations) == 1
        v = violations[0]
        # Anchored on the second file in (path, line) sort order: CLAUDE.md
        assert v.file_path.name == "CLAUDE.md"
        heading_line = claude_content.splitlines().index("## Testing workflow") + 1
        assert v.file_line == heading_line
        assert "% similar" in v.message
        assert "AGENTS.md:5" in v.message
        assert "Testing workflow" in v.message

    def test_identical_sections_pass(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_html_comment_and_whitespace_add_no_drift_distance(self, temp_dir):
        # A suppression directive (or any comment) plus extra blank lines in
        # one copy of an otherwise-identical section must not create drift.
        commented = _DRIFT_SECTION.replace(
            "## Testing workflow\n",
            "## Testing workflow\n\n<!-- skillsaw-disable some-other-rule -->\n\n\n",
            1,
        )
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + commented)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_html_comment_does_not_mask_real_drift(self, temp_dir):
        # Comments are blanked before comparison, so one cannot dilute the
        # similarity of a genuinely drifted pair below the threshold.
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(
            _DRIFT_PREAMBLE
            + _DRIFT_SECTION_EDITED.replace(
                "## Testing workflow\n",
                "## Testing workflow\n\n<!-- reviewers: keep in sync -->\n\n",
                1,
            )
        )
        context = RepositoryContext(temp_dir)
        violations = ContentInstructionDriftRule().check(context)
        assert len(violations) == 1
        assert "% similar" in violations[0].message

    def test_dissimilar_sections_pass(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + """## Testing workflow

All unit specs live under `spec/` and run through the bundled rake
target. Coverage reports upload to the internal dashboard on merge, so
regressions surface within an hour. When adding a fixture, prefer
factories over static YAML dumps and document any external service the
scenario touches in the fixture header comment block.
""")
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_short_sections_skipped(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("## Style\n\nUse ruff. Run make format before push.\n")
        (temp_dir / "CLAUDE.md").write_text(
            "## Style\n\nUse ruff. Run make format before pushing.\n"
        )
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_single_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_code_blocks_do_not_participate(self, temp_dir):
        """Drift confined to fenced code is invisible: read_body strips code."""
        code_a = "```bash\nmake docker-up && make test\n```\n"
        code_b = "```bash\nmake docker-up && make test -j4 --verbose\n```\n"
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION + code_a)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION + code_b)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []

    def test_generated_files_skipped_by_default(self, temp_dir):
        # Marker in its own tiny section so it doesn't dilute the compared one
        footer = "\n## About\n\n*This file was generated by APM CLI. Do not edit manually.*\n"
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION_EDITED + footer)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []
        violations = ContentInstructionDriftRule({"ignore-generated": False}).check(context)
        assert len(violations) == 1

    def test_apm_header_stamp_marks_file_generated(self, temp_dir):
        """APM stamps compiled copilot outputs with only '<!-- Generated by
        APM CLI from .apm/ primitives -->' — no 'do not edit' text anywhere
        in the file.  The stamped copy must not drift-compare against its
        own .apm/ source (regression: the marker regex previously required
        'do not edit' on the same line)."""
        repo = copy_content_fixture("instruction-drift-apm-generated", temp_dir)
        context = RepositoryContext(repo)
        assert ContentInstructionDriftRule().check(context) == []
        # The pair HAS drifted (the source gained a clause after the last
        # compile) — only the header stamp keeps the rule quiet.
        violations = ContentInstructionDriftRule({"ignore-generated": False}).check(context)
        assert len(violations) == 1
        assert "% similar" in violations[0].message

    def test_unmarked_near_copy_still_fires(self, temp_dir):
        """A hand-written near-copy with no generated marker keeps firing."""
        repo = copy_content_fixture("instruction-drift-apm-generated", temp_dir)
        copilot = repo / ".github" / "copilot-instructions.md"
        unmarked = "\n".join(
            line
            for line in copilot.read_text().splitlines()
            if "Generated by APM CLI" not in line and "Build ID" not in line
        )
        copilot.write_text(unmarked.lstrip("\n") + "\n")
        violations = ContentInstructionDriftRule().check(RepositoryContext(repo))
        assert len(violations) == 1
        assert violations[0].file_path.name == "copilot-instructions.md"

    def test_similarity_max_sections_caps_comparison(self, temp_dir):
        """Sections beyond the cap (in path order) skip pairwise comparison."""
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + """## Testing workflow

All unit specs live under `spec/` and run through the bundled rake
target. Coverage reports upload to the internal dashboard on merge, so
regressions surface within an hour. When adding a fixture, prefer
factories over static YAML dumps and document any external service the
scenario touches in the fixture header comment block.
""")
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "GEMINI.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION_EDITED)
        context = RepositoryContext(temp_dir)
        assert len(ContentInstructionDriftRule().check(context)) == 1
        # cap=2 keeps only the AGENTS.md and CLAUDE.md sections; the
        # drifted GEMINI.md copy is never compared.
        rule = ContentInstructionDriftRule({"similarity-max-sections": 2})
        assert rule.check(context) == []
        assert (
            ContentInstructionDriftRule.config_schema["similarity-max-sections"]["default"] == 400
        )

    def test_invalid_similarity_max_sections_rejected(self):
        with pytest.raises(ValueError, match="similarity-max-sections"):
            ContentInstructionDriftRule({"similarity-max-sections": 1})
        with pytest.raises(ValueError, match="similarity-max-sections"):
            ContentInstructionDriftRule({"similarity-max-sections": "many"})

    @pytest.mark.parametrize("bad_threshold", [0, 1.5])
    def test_invalid_threshold_rejected(self, bad_threshold):
        with pytest.raises(ValueError, match="similarity-threshold"):
            ContentInstructionDriftRule({"similarity-threshold": bad_threshold})

    def test_invalid_min_section_words_rejected(self):
        with pytest.raises(ValueError, match="min-section-words"):
            ContentInstructionDriftRule({"min-section-words": 0})

    def test_custom_threshold_honored(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION)
        (temp_dir / "CLAUDE.md").write_text(_DRIFT_PREAMBLE + _DRIFT_SECTION_EDITED)
        context = RepositoryContext(temp_dir)
        assert ContentInstructionDriftRule().check(context)
        rule = ContentInstructionDriftRule({"similarity-threshold": 0.95})
        assert rule.check(context) == []


class TestContentBrokenInternalReferenceRule:
    def test_rule_metadata(self):
        rule = ContentBrokenInternalReferenceRule()
        assert rule.rule_id == "content-broken-internal-reference"
        assert rule.default_severity() == Severity.WARNING

    def test_existing_file_no_violation(self, temp_dir):
        (temp_dir / "guide.md").write_text("# Guide\nContent here.\n")
        (temp_dir / "CLAUDE.md").write_text("See [the guide](guide.md) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_missing_file_violation(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See [the guide](missing-guide.md) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "missing-guide.md" in violations[0].message
        assert violations[0].line == 1

    def test_url_links_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "See [docs](https://example.com/docs) and [other](http://example.com).\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_anchor_links_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See [section](#overview) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_template_dir_skipped(self, temp_dir):
        tmpl_dir = temp_dir / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "CLAUDE.md").write_text("See [placeholder](nonexistent.md) for details.\n")
        # Need a SKILL.md to make it an agentskills repo so the rule applies
        (temp_dir / "SKILL.md").write_text("---\nname: test\n---\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_reports_line_number(self, temp_dir):
        content = "Line 1\nLine 2\nSee [broken](no-such-file.md).\nLine 4\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_link_with_anchor_existing_file(self, temp_dir):
        (temp_dir / "guide.md").write_text("# Guide\n## Section\n")
        (temp_dir / "CLAUDE.md").write_text("See [section](guide.md#section).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_multiple_broken_links(self, temp_dir):
        content = "See [a](missing-a.md) and [b](missing-b.md).\n" "Also [c](missing-c.md).\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 3

    def test_path_traversal_outside_repo(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See [escape](../../etc/passwd) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "outside repository" in violations[0].message

    def test_link_with_title_text(self, temp_dir):
        """Links with optional title text should resolve correctly."""
        (temp_dir / "guide.md").write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text(
            'See [the guide](guide.md "Intro guide") for details.\n'
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_inline_code_spans_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use `([Prow]({prow_url}) | [Intervals]({sippy_url}))` for links.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_double_backtick_code_spans_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use ``[broken](nonexistent.md)`` in your template.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_multiline_code_span_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use `some code\n[broken](nonexistent.md)\nmore code` in your template.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_percent_encoded_link_to_existing_file(self, temp_dir):
        """Regression for #322: a %20 link to a real file is not broken."""
        refs = temp_dir / "references"
        refs.mkdir()
        (refs / "style guide.md").write_text("# Style Guide\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Follow [the style guide](references/style%20guide.md) for docs.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert violations == []

    def test_percent_encoded_link_to_missing_file(self, temp_dir):
        """A genuinely broken %20 link still fires, keeping the original
        destination text in the message."""
        (temp_dir / "CLAUDE.md").write_text(
            "Follow [the style guide](references/style%20guide.md) for docs.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "references/style%20guide.md" in violations[0].message

    def test_percent_encoded_link_with_anchor(self, temp_dir):
        (temp_dir / "style guide.md").write_text("# Style Guide\n## Voice\n")
        (temp_dir / "CLAUDE.md").write_text("See [voice](style%20guide.md#voice).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert violations == []

    def test_literal_percent_sequence_in_filename_linked_verbatim(self, temp_dir):
        """A file whose literal name contains %XX, linked verbatim, linted
        clean before decoding existed — decoding must not break it."""
        refs = temp_dir / "refs"
        refs.mkdir()
        (refs / "x%20y.md").write_text("# Literal percent\n")
        (temp_dir / "CLAUDE.md").write_text("See [notes](refs/x%20y.md) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert violations == []

    def test_double_encoded_link_to_literal_percent_filename(self, temp_dir):
        """%2520 decodes once to %20, matching a literal %20 in the name."""
        (temp_dir / "x%20y.md").write_text("# Literal percent\n")
        (temp_dir / "CLAUDE.md").write_text("See [notes](x%2520y.md) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert violations == []

    def test_literal_percent_not_a_valid_escape(self, temp_dir):
        """A bare % that is not a valid escape (50%.md, w%zz.md) passes
        through unquote unchanged and resolves literally."""
        (temp_dir / "50%.md").write_text("# Fifty\n")
        (temp_dir / "w%zz.md").write_text("# Malformed escape\n")
        (temp_dir / "CLAUDE.md").write_text("See [fifty](50%.md) and [malformed](w%zz.md).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert violations == []

    def test_undecodable_destination_reports_broken(self, temp_dir):
        """An embedded %00 decodes to NUL, which cannot resolve — report
        broken instead of crashing."""
        (temp_dir / "CLAUDE.md").write_text("See [bad](refs%00/x.md).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "refs%00/x.md" in violations[0].message

    @pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
    def test_circular_symlink_reports_broken_not_crash(self, temp_dir):
        """A self-referential symlink cannot resolve — Path.resolve()
        raises RuntimeError on Python <= 3.12; report broken instead of
        crashing."""
        loop = temp_dir / "loop.md"
        loop.symlink_to(loop)
        (temp_dir / "CLAUDE.md").write_text("See [loop](loop.md).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "does not exist" in violations[0].message

    @pytest.mark.skipif(os.name == "nt", reason="backslash is a separator on Windows")
    def test_literal_backslash_filename_suggestion_preserved(self, temp_dir):
        """On POSIX a literal backslash is part of the file name — the
        Windows separator normalization (as_posix) must not rewrite it."""
        (temp_dir / "style\\guide.md").write_text("# Style\n")
        (temp_dir / "CLAUDE.md").write_text("See [style](style-guide.md).\n")
        context = RepositoryContext(temp_dir)
        violations = ContentBrokenInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "did you mean 'style\\guide.md'?" in violations[0].message


class TestContentUnlinkedInternalReferenceRule:
    def test_rule_metadata(self):
        rule = ContentUnlinkedInternalReferenceRule()
        assert rule.rule_id == "content-unlinked-internal-reference"
        assert rule.default_severity() == Severity.INFO

    def test_bare_path_violation(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Check the file at src/config/settings.yaml for defaults.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "src/config/settings.yaml" in violations[0].message

    def test_path_in_link_syntax_no_violation(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Check the [settings](src/config/settings.yaml) for defaults.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_dot_slash_path(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Run ./scripts/build.sh to build.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "./scripts/build.sh" in violations[0].message

    def test_path_abutting_close_paren_not_flagged(self, temp_dir):
        """Regression for #321: `scripts/test.pyc)` must not backtrack to a
        truncated `scripts/test.py` match."""
        (temp_dir / "scripts").mkdir()
        (temp_dir / "scripts" / "test.py").write_text("# test\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Run the helper (e.g. scripts/test.pyc) before committing.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert violations == []

    def test_path_abutting_open_paren_not_mangled(self, temp_dir):
        """Regression for #321: `(docs/guide.md)` must not produce a mangled
        `ocs/guide.md`-style match one character in."""
        (temp_dir / "CLAUDE.md").write_text("See the guide (docs/guide.md) for details.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert violations == []

    def test_dot_slash_path_does_not_swallow_sentence_period(self, temp_dir):
        """Regression for #321: `./docs/guide.md.` at the end of a sentence
        must match `./docs/guide.md`, not include the period."""
        (temp_dir / "CLAUDE.md").write_text("See ./docs/guide.md. Then continue.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "'./docs/guide.md'" in violations[0].message

    def test_code_blocks_skipped(self, temp_dir):
        content = "# Rules\n```\nsrc/config/settings.yaml\n```\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_url_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Visit https://example.com/path/to/file.html for more.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0, f"URL path fragment should not be flagged, got: {violations}"

    def test_custom_patterns_config(self, temp_dir):
        """Test that custom patterns config filters which paths are flagged."""
        (temp_dir / "CLAUDE.md").write_text(
            "See docs/guide.md for info.\nAlso check src/config/settings.yaml.\n"
        )
        context = RepositoryContext(temp_dir)
        # With default patterns, both should be flagged
        rule_default = ContentUnlinkedInternalReferenceRule()
        violations = rule_default.check(context)
        assert len(violations) == 2

        # With restricted patterns, only .yaml paths should match
        rule_custom = ContentUnlinkedInternalReferenceRule()
        rule_custom.config = {"patterns": ["*.yaml"]}
        violations = rule_custom.check(context)
        assert len(violations) == 1
        assert "settings.yaml" in violations[0].message

    def test_empty_patterns_config_no_violations(self, temp_dir):
        """Test that empty patterns list results in no violations."""
        (temp_dir / "CLAUDE.md").write_text("See docs/guide.md for info.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        rule.config = {"patterns": []}
        violations = rule.check(context)
        assert len(violations) == 0

    def test_reports_line_number(self, temp_dir):
        content = "Line 1\nLine 2\nSee docs/guide.md for info.\nLine 4\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line == 3

    def test_at_import_lines_not_flagged(self, temp_dir):
        """@import lines should not trigger unlinked-internal-reference (regression)."""
        (temp_dir / "CLAUDE.md").write_text("@nonexistent/missing-package.md\n")
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_backtick_path_not_flagged(self, temp_dir):
        """Paths inside inline code spans should not trigger violations."""
        (temp_dir / "CLAUDE.md").write_text(
            "Read the template at `${CLAUDE_SKILL_DIR}/prompts/analyze-skill.md` for the full schema.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_double_backtick_exact_path_flagged(self, temp_dir):
        """A path that is the entire content of a double-backtick span should still be flagged."""
        (temp_dir / "CLAUDE.md").write_text(
            "You can also reference ``prompts/analyze-skill.md`` with double backticks.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "prompts/analyze-skill.md" in violations[0].message

    def test_bare_path_next_to_backtick_path_flagged(self, temp_dir):
        """A bare path on the same line as a backtick-quoted path should still be flagged."""
        (temp_dir / "prompts").mkdir()
        (temp_dir / "prompts" / "analyze-skill.md").write_text("# Prompt\n")
        (temp_dir / "CLAUDE.md").write_text(
            "See `${CLAUDE_SKILL_DIR}/prompts/analyze-skill.md` and prompts/analyze-skill.md for details.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 1
        assert "prompts/analyze-skill.md" in violations[0].message

    def test_fenced_code_block_path_not_flagged(self, temp_dir):
        """Paths inside fenced code blocks should not trigger violations."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Guide\n\n" "```\n" "prompts/analyze-skill.md\n" "```\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_tilde_fenced_code_block_path_not_flagged(self, temp_dir):
        """Paths inside ~~~ fenced code blocks should not trigger violations."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Guide\n\n" "~~~\n" "prompts/analyze-skill.md\n" "~~~\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_html_comment_path_not_flagged(self, temp_dir):
        """Paths inside HTML comments should not trigger violations."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Guide\n\n" "<!-- This references prompts/analyze-skill.md internally -->\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_multiline_html_comment_path_not_flagged(self, temp_dir):
        """Paths inside multi-line HTML comments should not trigger violations."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Guide\n\n" "<!--\n" "prompts/analyze-skill.md\n" "-->\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentUnlinkedInternalReferenceRule().check(context)
        assert len(violations) == 0


class TestContentPlaceholderTextRule:
    def test_rule_metadata(self):
        rule = ContentPlaceholderTextRule()
        assert rule.rule_id == "content-placeholder-text"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_todo(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("TODO: add error handling.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "TODO" in violations[0].message

    def test_detects_fixme(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("FIXME: broken logic here.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "FIXME" in violations[0].message

    def test_detects_xxx(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("XXX: needs review.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "XXX" in violations[0].message

    def test_detects_link_here(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See [link here] for more info.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "Placeholder link" in violations[0].message

    def test_detects_insert_placeholder(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Add your [Insert API key] to the config.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "Insert placeholder" in violations[0].message

    def test_detects_if_placeholder(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "[If using Docker, add Docker setup instructions here]\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "Conditional placeholder" in violations[0].message

    def test_detects_will_be_added(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("More details *to be added*.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "Unfilled template" in violations[0].message

    def test_detects_tbd(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Configuration *TBD*.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert "Unfilled template" in violations[0].message

    def test_will_be_added_in_changelog_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Feature X *will be added in v2.0*.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        # The tightened regex should not flag general "will be added" text
        assert len(violations) == 0

    def test_will_be_added_as_you_use_not_flagged(self, temp_dir):
        """'will be added as you use' is normal prose, not placeholder text."""
        (temp_dir / "CLAUDE.md").write_text("Memories *will be added as you use* the tool.\n")
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 0

    def test_clean_content_no_violations(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\nUse 4-space indentation.\nReturn 404 for missing resources.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 0

    def test_reports_line_number(self, temp_dir):
        content = "Line 1\nLine 2\nTODO: fix this\nLine 4\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_code_blocks_skipped(self, temp_dir):
        content = "# Rules\n```\nTODO: fix this\nFIXME: broken\n```\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 0

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = ContentPlaceholderTextRule().check(context)
        assert len(violations) == 0


class TestContentUnlinkedInternalReferenceAutofix:
    def test_autofix_wraps_existing_path(self, temp_dir):
        """Bare paths to existing files should be autofixed with SAFE confidence."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "guide.md").write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text("See docs/guide.md for info.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "autofixable" in violations[0].message
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "[docs/guide.md](docs/guide.md)" in fixes[0].fixed_content

    def test_autofix_preserves_paren_adjacent_and_period_adjacent_paths(self, temp_dir):
        """Regression for #321: fix must not corrupt `scripts/test.pyc)` and
        must keep a sentence-ending period outside the link."""
        (temp_dir / "scripts").mkdir()
        (temp_dir / "scripts" / "test.py").write_text("# test\n")
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "guide.md").write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Run the helper (e.g. scripts/test.pyc) before committing.\n"
            "See ./docs/guide.md. Then run scripts/test.py to validate.\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert "(e.g. scripts/test.pyc)" in fixed
        assert "See [./docs/guide.md](./docs/guide.md)." in fixed
        assert "run [scripts/test.py](scripts/test.py) to validate" in fixed
        assert len(fixed.splitlines()) == 2

    def test_no_autofix_for_nonexistent_path(self, temp_dir):
        """Bare paths to nonexistent files should not be autofixed."""
        (temp_dir / "CLAUDE.md").write_text("See docs/guide.md for info.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "autofixable" not in violations[0].message
        fixes = rule.fix(context, violations)
        assert len(fixes) == 0

    def test_autofix_duplicate_paths_no_double_wrap(self, temp_dir):
        """When the same path appears multiple times, each should be wrapped independently."""
        (temp_dir / "scripts").mkdir()
        (temp_dir / "scripts" / "test.py").write_text("# test\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Use the `scripts/test.py` script to do a review\n\n"
            "Re-run script `scripts/test.py` again for some reason\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 2
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert fixed.count("[`scripts/test.py`](scripts/test.py)") == 2
        assert "[[" not in fixed

    def test_autofix_triple_duplicate_no_double_wrap(self, temp_dir):
        """Three occurrences of the same path should each be wrapped exactly once."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("# main\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Run src/main.py first\n\n"
            "Then check src/main.py for errors\n\n"
            "Finally re-run src/main.py\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 3
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert fixed.count("[src/main.py](src/main.py)") == 3
        assert "[[src/main.py]" not in fixed
        assert "](src/main.py)](src/main.py)" not in fixed

    def test_autofix_multiple_different_paths(self, temp_dir):
        """Multiple different bare paths should each be wrapped independently."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "guide.md").write_text("# Guide\n")
        (temp_dir / "scripts").mkdir()
        (temp_dir / "scripts" / "run.sh").write_text("#!/bin/bash\n")
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "app.py").write_text("# app\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Read docs/guide.md for setup\n\n"
            "Run scripts/run.sh to build\n\n"
            "Edit src/app.py for logic\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 3
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert "[docs/guide.md](docs/guide.md)" in fixed
        assert "[scripts/run.sh](scripts/run.sh)" in fixed
        assert "[src/app.py](src/app.py)" in fixed
        assert fixed.count("[[") == 0

    def test_autofix_mixed_autofixable_and_nonexistent(self, temp_dir):
        """Only existing paths should be fixed; nonexistent paths left alone."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "real.py").write_text("# real\n")
        (temp_dir / "CLAUDE.md").write_text(
            "See src/real.py for implementation\n\n" "See src/fake.py for nothing\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 2
        autofixable = [v for v in violations if "autofixable" in v.message]
        assert len(autofixable) == 1
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert "[src/real.py](src/real.py)" in fixed
        assert "src/fake.py" in fixed
        assert "[src/fake.py]" not in fixed

    def test_autofix_mixed_duplicates_and_different_paths(self, temp_dir):
        """Mix of duplicate and unique paths: all wrapped, none double-wrapped."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("# main\n")
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "api.md").write_text("# API\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Start with src/main.py\n\n"
            "Read docs/api.md for reference\n\n"
            "Re-run src/main.py after changes\n\n"
            "Check docs/api.md for updates\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 4
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert fixed.count("[src/main.py](src/main.py)") == 2
        assert fixed.count("[docs/api.md](docs/api.md)") == 2
        assert "[[" not in fixed
        assert "](src/main.py)](src/main.py)" not in fixed
        assert "](docs/api.md)](docs/api.md)" not in fixed

    def test_autofix_idempotent(self, temp_dir):
        """Applying fix twice produces identical content — no double-wrapping."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("# main\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Run src/main.py first\n\nThen check src/main.py again\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        first_fixed = fixes[0].fixed_content
        assert first_fixed.count("[src/main.py](src/main.py)") == 2
        assert "[[" not in first_fixed
        fixes[0].file_path.write_text(first_fixed, encoding="utf-8")
        context2 = RepositoryContext(temp_dir)
        violations2 = rule.check(context2)
        fixes2 = rule.fix(context2, violations2)
        if fixes2:
            assert fixes2[0].fixed_content == first_fixed

    def test_autofix_skips_backtick_paths(self, temp_dir):
        """Paths inside backtick spans should not be modified by autofix."""
        (temp_dir / "prompts").mkdir()
        (temp_dir / "prompts" / "analyze-skill.md").write_text("# Prompt\n")
        (temp_dir / "CLAUDE.md").write_text(
            "Read the template at `${CLAUDE_SKILL_DIR}/prompts/analyze-skill.md` for the full schema.\n\n"
            "For bare references, see prompts/analyze-skill.md directly.\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentUnlinkedInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "prompts/analyze-skill.md" in violations[0].message
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert "`${CLAUDE_SKILL_DIR}/prompts/analyze-skill.md`" in fixed
        assert "[prompts/analyze-skill.md](prompts/analyze-skill.md)" in fixed

    def test_supports_autofix_property(self):
        rule = ContentUnlinkedInternalReferenceRule()
        assert rule.supports_autofix


class TestContentBrokenInternalReferenceAutofix:
    def test_suggests_similar_filename(self, temp_dir):
        """Broken link should suggest a similar existing file."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "setup.md").write_text("# Setup\n")
        (temp_dir / "CLAUDE.md").write_text("See [guide](docs/setpu.md) for setup.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "did you mean" in violations[0].message

    def test_suggests_moved_file(self, temp_dir):
        """Broken link should suggest exact name match in different directory."""
        (temp_dir / "reference").mkdir()
        (temp_dir / "reference" / "guide.md").write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text("See [guide](docs/guide.md) for help.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "did you mean" in violations[0].message

    def test_fix_applies_suggestion(self, temp_dir):
        """Fix should replace broken link target with the suggestion."""
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "setup.md").write_text("# Setup\n")
        (temp_dir / "CLAUDE.md").write_text("See [guide](docs/setpu.md) for setup.\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert "docs/setpu.md" not in fixes[0].fixed_content

    def test_supports_autofix_property(self):
        rule = ContentBrokenInternalReferenceRule()
        assert rule.supports_autofix

    def test_fix_reference_definition(self, temp_dir):
        """Fix should rewrite the reference definition destination, not the usage."""
        (temp_dir / "guide.md").write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text("See [the guide][g] for help.\n\n[g]: docs/guide.md\n")
        context = RepositoryContext(temp_dir)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "did you mean" in violations[0].message
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        fixed = fixes[0].fixed_content
        assert "[g]: guide.md" in fixed
        assert "[the guide][g]" in fixed

    def test_no_suggestion_when_no_similar_file(self, temp_dir):
        """No suggestion when no similar file exists."""
        (temp_dir / "CLAUDE.md").write_text(
            "See [guide](totally/unique/nonexistent.xyz) for info.\n"
        )
        context = RepositoryContext(temp_dir)
        rule = ContentBrokenInternalReferenceRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "did you mean" not in violations[0].message


class TestContentUnclosedFenceRule:
    def _check(self, temp_dir):
        return ContentUnclosedFenceRule().check(RepositoryContext(temp_dir))

    def test_rule_metadata(self):
        rule = ContentUnclosedFenceRule()
        assert rule.rule_id == "content-unclosed-fence"
        assert rule.default_severity() == Severity.WARNING
        assert rule.autofix_confidence == AutofixConfidence.SUGGEST
        assert rule.supports_autofix

    def test_detects_unclosed_fence(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n```bash\nmake test\n\nAlways run the linter before pushing.\n"
        )
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].line == 3
        assert "```bash" in violations[0].message

    def test_closed_fence_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Rules\n\n```bash\nmake test\n```\n")
        assert self._check(temp_dir) == []

    def test_closed_fence_at_eof_without_trailing_newline(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```bash\nmake test\n```")
        assert self._check(temp_dir) == []

    def test_unclosed_fence_without_trailing_newline(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```bash\nmake test")
        assert len(self._check(temp_dir)) == 1

    def test_unclosed_fence_with_trailing_blank_lines(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```bash\nmake test\n\n\n")
        assert len(self._check(temp_dir)) == 1

    def test_longer_closer_run_closes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```\ncode\n`````\n")
        assert self._check(temp_dir) == []

    def test_shorter_closer_does_not_close(self, temp_dir):
        # A three-backtick run cannot close a four-backtick fence.
        (temp_dir / "CLAUDE.md").write_text("````markdown\n```\ncode\n```\n")
        assert len(self._check(temp_dir)) == 1

    def test_four_backtick_fence_with_inner_fences_closed(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("````markdown\n```bash\nmake test\n```\n````\n")
        assert self._check(temp_dir) == []

    def test_tilde_fence_unclosed(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("~~~python\nprint('hi')\n")
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert "~~~python" in violations[0].message

    def test_tilde_fence_closed(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("~~~python\nprint('hi')\n~~~\n")
        assert self._check(temp_dir) == []

    def test_closer_with_trailing_spaces_and_indent(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```\ncode\n   ```  \n")
        assert self._check(temp_dir) == []

    def test_pseudo_closer_with_info_string_flagged(self, temp_dir):
        # "``` bash" has an info string, which a closing fence cannot have.
        (temp_dir / "CLAUDE.md").write_text("```bash\ncode\n``` bash\n")
        assert len(self._check(temp_dir)) == 1

    def test_indented_code_block_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Paragraph.\n\n    indented code\n    more code\n")
        assert self._check(temp_dir) == []

    def test_blockquote_nested_fence_not_flagged(self, temp_dir):
        # Out of scope: a column-0 closer would not terminate it.
        (temp_dir / "CLAUDE.md").write_text("> ```\n> code\n")
        assert self._check(temp_dir) == []

    def test_list_nested_fence_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("- item\n  ```\n  code\n")
        assert self._check(temp_dir) == []

    def test_fence_closed_mid_file_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("```\ncode\n```\n\nProse after the block.\n")
        assert self._check(temp_dir) == []

    def test_no_files_no_violations(self, temp_dir):
        assert self._check(temp_dir) == []

    def test_yaml_embedded_body_reported_not_fixable(self, temp_dir):
        """check() must not advertise a fix for YAML-embedded bodies that
        fix() always skips (.coderabbit path_instructions) — regression
        for the '[?] fixable with skillsaw fix --suggest' over-promise."""
        repo = copy_content_fixture("unclosed-fence-coderabbit", temp_dir)
        violations = ContentUnclosedFenceRule().check(RepositoryContext(repo))
        by_name = {v.file_path.name: v for v in violations}
        assert set(by_name) == {".coderabbit.yaml", "CLAUDE.md"}
        yaml_violation = by_name[".coderabbit.yaml"]
        assert yaml_violation.fixable is False
        assert yaml_violation.fix_confidence is None
        # Standalone markdown bodies keep the fixable promise.
        md_violation = by_name["CLAUDE.md"]
        assert md_violation.fixable is True
        assert md_violation.fix_confidence == AutofixConfidence.SUGGEST


class TestContentUnclosedFenceAutofix:
    def _fix(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = ContentUnclosedFenceRule()
        return rule.fix(context, rule.check(context))

    def test_fix_appends_closer(self, temp_dir):
        content = "# Rules\n\n```bash\nmake test\n\nRun the linter before pushing.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        fixes = self._fix(temp_dir)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert fixes[0].fixed_content == content + "```\n"

    def test_fix_adds_newline_when_missing(self, temp_dir):
        content = "```bash\nmake test"
        (temp_dir / "CLAUDE.md").write_text(content)
        fixes = self._fix(temp_dir)
        assert len(fixes) == 1
        assert fixes[0].fixed_content == content + "\n```\n"

    def test_fix_uses_matching_markup(self, temp_dir):
        content = "````markdown\n```bash\nmake test\n```\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        fixes = self._fix(temp_dir)
        assert len(fixes) == 1
        assert fixes[0].fixed_content == content + "````\n"

    def test_fix_uses_tilde_markup(self, temp_dir):
        content = "~~~python\nprint('hi')\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        fixes = self._fix(temp_dir)
        assert len(fixes) == 1
        assert fixes[0].fixed_content == content + "~~~\n"

    def test_fixed_content_lints_clean(self, temp_dir):
        from skillsaw.utils import invalidate_read_caches

        content = "# Rules\n\n```bash\nmake test\n\nRun the linter before pushing.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        fixes = self._fix(temp_dir)
        assert len(fixes) == 1

        (temp_dir / "CLAUDE.md").write_text(fixes[0].fixed_content)
        invalidate_read_caches()
        assert ContentUnclosedFenceRule().check(RepositoryContext(temp_dir)) == []

    def test_fix_skips_yaml_embedded_and_converges(self, temp_dir):
        """fix() repairs exactly the violations advertised as fixable:
        the standalone CLAUDE.md converges, the YAML-embedded one stays
        reported (and stays not-fixable)."""
        from skillsaw.utils import invalidate_read_caches

        repo = copy_content_fixture("unclosed-fence-coderabbit", temp_dir)
        fixes = self._fix(repo)
        assert [f.file_path.name for f in fixes] == ["CLAUDE.md"]

        (repo / "CLAUDE.md").write_text(fixes[0].fixed_content)
        invalidate_read_caches()
        remaining = ContentUnclosedFenceRule().check(RepositoryContext(repo))
        assert [v.file_path.name for v in remaining] == [".coderabbit.yaml"]
        assert remaining[0].fixable is False
        # Idempotent: a second fix pass has nothing left to do.
        assert self._fix(repo) == []


class TestContentRepeatedDirectiveRule:
    def test_rule_metadata(self):
        rule = ContentRepeatedDirectiveRule()
        assert rule.rule_id == "content-repeated-directive"
        assert rule.default_severity() == Severity.WARNING

    def test_detects_exact_duplicate_directive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "## Testing\n\n"
            "- Run `make test` before every push.\n"
            "- Mark slow tests with the `slow` marker for CI sharding.\n\n"
            "## Releases\n\n"
            "- Update the changelog in the same PR as the change.\n"
            "- Run `make test` before every push.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 11
        assert "repeats the directive at line 5" in violations[0].message

    def test_detects_near_duplicate_directive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Always run make test before pushing your changes.\n\n"
            "## Later\n\n"
            "Always run make test before pushing the changes.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "% similar" in violations[0].message

    def test_distinct_directives_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Run `make lint` before opening a PR.\n"
            "- Run `make test` before every push.\n"
            "- Use 4-space indentation in Python files.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_inline_code_distinguishes_directives(self, temp_dir):
        """Two directives differing only in their code span are distinct."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Run `make lint` before every push.\n"
            "- Run `make test` before every push.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_approval_cluster_restatement(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Ask before force-pushing to shared branches.\n\n"
            "## Deployments\n\n"
            "Wait for approval before deleting production resources.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 7
        assert "approval policy" in violations[0].message
        # Cluster restatements are review prompts, not defects — always INFO.
        assert violations[0].severity == Severity.INFO
        assert "line 3" in violations[0].message

    def test_code_blocks_not_scanned(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "```\n"
            "- Run `make test` before every push.\n"
            "- Run `make test` before every push.\n"
            "```\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_min_directive_words_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n" "- Run all the tests.\n\n" "## Later\n\n" "- Run all the tests.\n"
        )
        rule = ContentRepeatedDirectiveRule({"min-directive-words": 5})
        assert rule.check(RepositoryContext(temp_dir)) == []
        rule = ContentRepeatedDirectiveRule({"min-directive-words": 4})
        assert len(rule.check(RepositoryContext(temp_dir))) == 1

    def test_extra_clusters_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Deploy only from the main branch.\n\n"
            "## Later\n\n"
            "Ship exclusively from the main branch.\n"
        )
        rule = ContentRepeatedDirectiveRule(
            {"extra-clusters": {"deploy-source": [r"\b(?:deploy|ship)\s+(?:only|exclusively)\b"]}}
        )
        violations = rule.check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "deploy-source policy" in violations[0].message

    def test_invalid_threshold_rejected(self):
        with pytest.raises(ValueError, match="similarity-threshold"):
            ContentRepeatedDirectiveRule({"similarity-threshold": 0})
        with pytest.raises(ValueError, match="similarity-threshold"):
            ContentRepeatedDirectiveRule({"similarity-threshold": "high"})

    def test_invalid_extra_cluster_pattern_rejected(self):
        with pytest.raises(ValueError, match="Invalid pattern"):
            ContentRepeatedDirectiveRule({"extra-clusters": {"bad": ["("]}})
        with pytest.raises(ValueError, match="must be a mapping"):
            ContentRepeatedDirectiveRule({"extra-clusters": ["not-a-dict"]})

    def test_no_files_no_violations(self, temp_dir):
        assert ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir)) == []


class TestContentEmphasisDensityRule:
    def test_rule_metadata(self):
        rule = ContentEmphasisDensityRule()
        assert rule.rule_id == "content-emphasis-density"
        assert rule.default_severity() == Severity.WARNING

    def test_flags_emphasis_inflation(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- IMPORTANT: run the tests before committing.\n"
            "- You MUST update the API spec when handlers change.\n"
            "- NEVER log request bodies.\n"
            "- ALWAYS regenerate mocks after interface edits.\n"
            "- CRITICAL: keep migrations reversible.\n"
        )
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line is None
        assert "5 of 6 lines" in violations[0].message

    def test_sparse_emphasis_passes(self, temp_dir):
        lines = [f"- Step {i}: check the {i} widget output.\n" for i in range(30)]
        content = "# Rules\n\n" + "".join(lines) + "- NEVER commit secrets.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_below_min_emphasized_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n- NEVER commit secrets.\n- ALWAYS run the tests.\n"
        )
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_lowercase_keywords_not_counted(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Never log request bodies.\n"
            "- Always regenerate mocks.\n"
            "- Never commit secrets.\n"
            "- Always run the tests first.\n"
            "- Never push directly to main.\n"
        )
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_code_blocks_not_counted(self, temp_dir):
        fence_lines = "".join(f"MUST_FLAG_{i} = True\n" for i in range(6))
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n```python\n" + fence_lines + "```\n\n- Run the tests.\n"
        )
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_config_validation(self):
        with pytest.raises(ValueError, match="max-ratio"):
            ContentEmphasisDensityRule({"max-ratio": 1.5})
        with pytest.raises(ValueError, match="min-emphasized"):
            ContentEmphasisDensityRule({"min-emphasized": 0})

    def test_max_ratio_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- IMPORTANT: run the tests before committing.\n"
            "- You MUST update the API spec when handlers change.\n"
            "- NEVER log request bodies.\n"
            "- ALWAYS regenerate mocks after interface edits.\n"
            "- CRITICAL: keep migrations reversible.\n"
        )
        rule = ContentEmphasisDensityRule({"max-ratio": 0.9})
        assert rule.check(RepositoryContext(temp_dir)) == []


class TestContentMissingStopConditionRule:
    def test_rule_metadata(self):
        rule = ContentMissingStopConditionRule()
        assert rule.rule_id == "content-missing-stop-condition"
        assert rule.default_severity() == Severity.WARNING
        assert rule.default_enabled is False

    def test_flags_open_ended_monitoring(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "After opening a PR, keep monitoring for reviewer feedback and\n"
            "address comments as they arrive.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 3
        assert "keep monitoring" in violations[0].message

    def test_terminator_in_same_paragraph_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "After opening a PR, keep monitoring for reviewer feedback.\n"
            "You may stop monitoring 20 minutes after you push.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_until_terminator_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nPoll for job completion until the pipeline finishes.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_bounded_retry_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Retry when the registry pull fails; give up after 3 attempts\n"
            "and page the infra channel instead.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_terminator_in_other_paragraph_does_not_count(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Keep polling the deployment status endpoint.\n\n"
            "Unrelated: wait until the cache warms before benchmarking.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_code_blocks_not_scanned(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Rules\n\n```\nkeep monitoring for feedback\n```\n")
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 0

    def test_extra_loop_patterns_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nBabysit the release pipeline after merging.\n"
        )
        rule = ContentMissingStopConditionRule({"extra-loop-patterns": [r"\bbabysit\b"]})
        violations = rule.check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "babysit" in violations[0].message.lower()

    def test_extra_terminator_patterns_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nKeep checking CI and hand off at end of shift.\n"
        )
        rule = ContentMissingStopConditionRule(
            {"extra-terminator-patterns": [r"\bend\s+of\s+shift\b"]}
        )
        assert rule.check(RepositoryContext(temp_dir)) == []

    def test_invalid_pattern_rejected(self):
        with pytest.raises(ValueError, match="Invalid pattern"):
            ContentMissingStopConditionRule({"extra-loop-patterns": ["("]})
        with pytest.raises(ValueError, match="must be a list"):
            ContentMissingStopConditionRule({"extra-terminator-patterns": "until"})

    def test_no_files_no_violations(self, temp_dir):
        assert ContentMissingStopConditionRule().check(RepositoryContext(temp_dir)) == []


class TestContentRepeatedDirectiveTuning:
    """Guards added after real-repo impact analysis (GPT-5.6 rule set)."""

    def test_enumeration_labels_not_directives(self, temp_dir):
        """'Run 2: ...' example-data lines are labels, not imperatives."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Analysis example\n\n"
            '- Run 2: Failed tests = ["api discovery should work"]\n'
            '- Run 3: Failed tests = ["api discovery should work"]\n\n'
            "## Later\n\n"
            '- Run 7: Failed tests = ["api discovery should work"]\n'
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_neighboring_parallel_bullets_not_flagged(self, temp_dir):
        """Similar bullets within min-line-distance are parallel structure."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Check the build log for compiler warnings today.\n"
            "- Check the build log for compiler errors today.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_min_line_distance_config(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Check the build log for compiler warnings today.\n"
            "- Check the build log for compiler errors today.\n"
        )
        rule = ContentRepeatedDirectiveRule({"min-line-distance": 1})
        assert len(rule.check(RepositoryContext(temp_dir))) == 1

    def test_invalid_min_line_distance_rejected(self):
        with pytest.raises(ValueError, match="min-line-distance"):
            ContentRepeatedDirectiveRule({"min-line-distance": 0})

    def test_line_matching_similarity_and_cluster_reported_once(self, temp_dir):
        """A line that is both a near-duplicate and a cluster match gets
        exactly one violation — the similarity pass claims it and the
        cluster pass honors the shared `reported` set."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Check with the user before deleting production data.\n\n"
            "## Cleanup\n\n"
            "Check with the user before deleting production files.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 7
        assert "% similar" in violations[0].message

    def test_bold_wrapped_duplicate_detected(self, temp_dir):
        """'- **Always run make test...**' stated twice — leading emphasis
        must not hide the verb from the imperative gate (regression)."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- **Always run make test before pushing any changes.**\n"
            "- Update the changelog in the same PR as the change.\n\n"
            "## Checklist\n\n"
            "- Mark slow tests with the `slow` marker.\n"
            "- **Always run make test before pushing any changes.**\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "repeats the directive at line 3" in violations[0].message

    def test_bold_and_plain_twin_detected(self, temp_dir):
        """A bolded directive and its unbolded twin normalize identically."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- **Never commit generated files to the main branch.**\n\n"
            "## Later\n\n"
            "- Never commit generated files to the main branch.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "repeats the directive at line 3" in violations[0].message

    def test_permission_errors_not_an_approval_policy(self, temp_dir):
        """Troubleshooting prose ('get permission errors') must not anchor
        the approval cluster — the real directive was flagged as
        restating a troubleshooting note (regression)."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "## Troubleshooting\n\n"
            "If you get permission errors when running the deploy script,\n"
            "check your kubeconfig points at the staging cluster.\n\n"
            "## Cleanup\n\n"
            "Ask before deleting any production resources.\n"
        )
        assert ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir)) == []

    def test_genuine_get_permission_directive_still_clusters(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Get permission before rotating the deploy credentials.\n\n"
            "## Cleanup\n\n"
            "Ask before deleting any production resources.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "approval policy" in violations[0].message

    def test_html_wrapped_fenced_examples_not_scanned(self, temp_dir):
        """<Bad>/<Good> fences with no blank line after the tag are
        swallowed into an html_block token — quoted example text inside
        them must not be scanned as live directives (regression)."""
        repo = copy_content_fixture("repeated-directive-html-example", temp_dir)
        assert ContentRepeatedDirectiveRule().check(RepositoryContext(repo)) == []

    def test_duplicate_outside_html_block_still_fires(self, temp_dir):
        """Blanking html-block fences must not hide real duplicates in
        the surrounding prose."""
        repo = copy_content_fixture("repeated-directive-html-example", temp_dir)
        claude = repo / "CLAUDE.md"
        claude.write_text(
            claude.read_text()
            + "\n## Publishing\n\n"
            + "Check the rendered output locally before opening a pull request.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(repo))
        assert len(violations) == 1
        assert "repeats the directive" in violations[0].message

    def test_similarity_cap_skips_pairwise_beyond_cap(self, temp_dir):
        """Directives beyond `similarity-max-directives` skip the O(n^2)
        similarity stage; exact repeats are still detected linearly."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "- Always run make test before pushing your changes.\n"
            "- Never commit generated files to the main branch.\n"
            "- Use four space indentation in Python source files.\n"
            "- Check the changelog entry format before merging.\n"
            "- Set the version bump label on every release PR.\n"
            "- Write regression tests for every bug fix you land.\n"
            "- Always run make test before pushing the changes.\n"
            "- Never commit generated files to the main branch.\n"
        )
        context = RepositoryContext(temp_dir)
        # Uncapped: the near-duplicate (line 9) and exact repeat (line 10).
        assert len(ContentRepeatedDirectiveRule().check(context)) == 2
        # Capped at 5 directives: lines 9-10 are beyond the cap.  The
        # exact repeat survives the linear scan; the near-duplicate is
        # no longer compared.
        rule = ContentRepeatedDirectiveRule({"similarity-max-directives": 5})
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].line == 10
        assert "repeats the directive at line 4" in violations[0].message

    def test_similarity_cap_default_covers_realistic_files(self):
        # Measured: a realistic 2000-line CLAUDE.md holds ~1150 directives;
        # the default cap must keep such files fully scanned.
        schema = ContentRepeatedDirectiveRule.config_schema
        assert schema["similarity-max-directives"]["default"] == 1500

    def test_invalid_similarity_max_directives_rejected(self):
        with pytest.raises(ValueError, match="similarity-max-directives"):
            ContentRepeatedDirectiveRule({"similarity-max-directives": 1})
        with pytest.raises(ValueError, match="similarity-max-directives"):
            ContentRepeatedDirectiveRule({"similarity-max-directives": True})


class TestContentMissingStopConditionTuning:
    """Guards added after real-repo impact analysis (GPT-5.6 rule set)."""

    def test_descriptive_continuously_not_flagged(self, temp_dir):
        """'continuously' describing system behavior is not a loop order."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Notes\n\n"
            "The sync daemon continuously reconnects to the message bus\n"
            "when the broker restarts.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_imperative_continuously_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nContinuously check the job queue for new entries.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1

    def test_watch_for_not_flagged(self, temp_dir):
        """'Watch for X' means 'be alert to X', not 'loop watching X'."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nWatch for crypto and TLS errors in FIPS clusters.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_table_rows_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "| Variant | Guidance |\n"
            "|---------|----------|\n"
            "| fips | Keep checking the crypto logs |\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_avoid_polling_prohibition_not_flagged(self, temp_dir):
        """'Avoid polling X' forbids the loop — no stop condition needed
        (regression: webhooks-over-polling advice was flagged)."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Avoid polling the status endpoint; use webhooks to receive\n"
            "deploy notifications from the pipeline.\n"
        )
        assert ContentMissingStopConditionRule().check(RepositoryContext(temp_dir)) == []

    def test_never_poll_prohibition_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Never poll the deployment API directly from scripts.\n\n"
            "Never poll in a loop; subscribe to the event stream instead.\n"
        )
        assert ContentMissingStopConditionRule().check(RepositoryContext(temp_dir)) == []

    def test_never_stop_polling_still_flagged(self, temp_dir):
        """'Never stop polling' double-negates into an unbounded loop."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nNever stop polling the job queue for new work items.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1

    def test_instead_of_polling_not_flagged(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nUse webhooks instead of polling the status endpoint.\n"
        )
        assert ContentMissingStopConditionRule().check(RepositoryContext(temp_dir)) == []

    def test_imperative_poll_still_flagged(self, temp_dir):
        """The prohibition guard must not swallow genuine loop orders."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\nPoll the status endpoint for deploy completion.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1

    def test_once_subordinator_does_not_suppress(self, temp_dir):
        """'Once the PR is open, keep monitoring ...' STARTS the loop;
        the leading 'Once' must not count as a stopping condition
        (regression: bare 'once' anywhere exempted the paragraph)."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Once the PR is open, keep monitoring the CI pipeline for new\n"
            "failures and rerun flaky jobs as needed.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert "keep monitoring" in violations[0].message

    @pytest.mark.parametrize(
        "text",
        [
            "Retry when the registry pull flakes, but only once per job.\n",
            "Keep checking the queue; if it stalls, rerun the drain job once.\n",
            "Retry when the fetch fails; retry once and then surface the error.\n",
        ],
    )
    def test_bounding_once_still_terminates(self, temp_dir, text):
        """'once' in bounding positions (verb-adjacent, 'only once',
        clause-final) still counts as a stop condition."""
        (temp_dir / "CLAUDE.md").write_text("# Rules\n\n" + text)
        assert ContentMissingStopConditionRule().check(RepositoryContext(temp_dir)) == []


class TestContentRuleFalsePositiveGuards:
    """Guards from the ai-helpers / prodsec-skills field review."""

    def test_colon_caption_before_fence_not_a_directive(self, temp_dir):
        """'Add to `X`:' introducing a code block is a caption — parallel
        sections repeat the caption while the code differs."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Setup\n\n"
            "## VS Code\n\n"
            "Add to `customizations.vscode.extensions`:\n\n"
            '```json\n["ms-python.python"]\n```\n\n'
            "## Vim\n\n"
            "Add to `customizations.vscode.extensions`:\n\n"
            '```json\n["vscodevim.vim"]\n```\n'
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_heading_not_a_cluster_policy_statement(self, temp_dir):
        """A heading naming an approval section is not a restatement of
        the policy stated in its body."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Skill\n\n"
            "### Step 4: Require Explicit Approval\n\n"
            "Before applying changes, show the diff.\n\n"
            "## Rules\n\n"
            "Require explicit confirmation before applying fixes.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_rfc2119_table_not_emphasis_inflation(self, temp_dir):
        """MUST in spec tables is RFC-2119 language, not steering emphasis."""
        (temp_dir / "CLAUDE.md").write_text(
            "# JWT validation\n\n"
            "Validate every claim in the table below.\n\n"
            "| Claim | Requirement |\n"
            "|-------|-------------|\n"
            "| `iss` | MUST match the issuer URL |\n"
            "| `aud` | MUST match the audience |\n"
            "| `exp` | MUST be under 15 minutes |\n"
            "| `jti` | MUST be unique |\n"
            "| `sub` | MUST identify the caller |\n"
        )
        violations = ContentEmphasisDensityRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_heading_not_a_loop_instruction(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Skill\n\n"
            "### Step 3: Poll for Bot Response\n\n"
            "Read the reply and stop once it arrives.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_caption_above_fence_not_a_loop_instruction(self, temp_dir):
        """A colon caption whose loop is operationalized (and bounded) in
        the code block below it is not an open-ended instruction."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Skill\n\n"
            "After posting the comment, poll for the bot reply:\n\n"
            "```bash\nfor i in {1..10}; do gh pr view; sleep 30; done\n```\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_third_person_loop_adverb_not_flagged(self, temp_dir):
        """'pollers continuously check' describes infrastructure."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Notes\n\n"
            "In-cluster pollers continuously check API availability, and\n"
            "the aggregator runs continuously during upgrades.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_passive_loop_adverb_not_flagged(self, temp_dir):
        """'the tool is run repeatedly' is descriptive, not imperative."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Notes\n\n" "Caching avoids redundant reanalysis when the tool is run repeatedly.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_html_comment_not_a_cluster_policy_statement(self, temp_dir):
        """Suppression directives and commented-out prose are not
        delivered to the agent — they can't restate a policy."""
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n"
            "Ask before force-pushing to shared branches.\n\n"
            "## Later\n\n"
            "<!-- old rule: wait for approval before deleting data -->\n"
            "Delete stale branches weekly.\n"
        )
        violations = ContentRepeatedDirectiveRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_html_comment_not_a_loop_instruction(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Rules\n\n<!-- keep monitoring disabled for now -->\nRead the logs.\n"
        )
        violations = ContentMissingStopConditionRule().check(RepositoryContext(temp_dir))
        assert violations == []

    def test_emphasis_message_shows_decimal_ratio(self, temp_dir):
        """A file just over the threshold must not render '20% exceeds
        the 20% limit' — the measured ratio shows one decimal."""
        lines = [f"- Step {i}: read the {i} widget log.\n" for i in range(23)]
        content = (
            "# Rules\n\n"
            + "".join(lines)
            + "- NEVER commit secrets.\n"
            + "- ALWAYS run the tests.\n"
            + "- You MUST update the spec.\n"
            + "- NEVER log request bodies.\n"
            + "- ALWAYS regenerate mocks.\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        violations = ContentEmphasisDensityRule({"max-ratio": 0.15}).check(
            RepositoryContext(temp_dir)
        )
        assert len(violations) == 1
        assert "17.2% exceeds the 15% limit" in violations[0].message
