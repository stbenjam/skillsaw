"""Tests for content intelligence rules."""

import json
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
    ContentBrokenInternalReferenceRule,
    ContentUnlinkedInternalReferenceRule,
    ContentPlaceholderTextRule,
)

# Stripe test keys built from parts to avoid triggering GitHub push protection
_STRIPE_SK = "sk" + "_live_" + "TESTFAKEKEYDONOTUSE00000"
_STRIPE_RK = "rk" + "_live_" + "TESTFAKEKEYDONOTUSE00000"


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


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
            "Use token ghp_abcdefghijklmnopqrstuvwxyz123456789012\n"
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
        content = "Line 1\nLine 2\nPassword: password='xK9$mQ2vLp8#nR4zW7@j'\nLine 4\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert violations[0].line == 3

    @pytest.mark.parametrize(
        "secret,expected_desc",
        [
            ("sk-ant-api03-abcdefghijklmnopqrst", "Anthropic API key"),
            ("ghr_abcdefghijklmnopqrstuvwxyz123456789012", "GitHub refresh token"),
            ("ASIAIOSFODNN7EXAMPLE", "AWS temporary access key"),
            ("xoxa-123456789012-abcdefghij", "Slack app token"),
            ("xoxr-123456789012-abcdefghij", "Slack refresh token"),
            (_STRIPE_SK, "Stripe secret key"),
            (_STRIPE_RK, "Stripe restricted key"),
            ("AIzaSyATESTFAKEKEYDONOTUSE0000000000000", "Google API key"),
            ("SK00000000000000000000000000000000", "Twilio API key"),
            (
                "SG.abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyz0123456789abcdefghijk",
                "SendGrid API key",
            ),
            ("npm_abcdefghijklmnopqrstuvwxyz1234567890", "npm access token"),
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
            'password = "dummy-value-123"',
            'api_key = "<your-api-key-goes-here>"',
            'api_key = "${MY_API_KEY_FROM_ENV}"',
            'api_key = "EXAMPLE_KEY_1234567890"',
            'api_key = "abababababababab"',
            'secret_key = "{{ secrets.PRODUCTION_KEY }}"',
            'access_token = "insert-real-value-here"',
            'password = "$DB_PASSWORD"',
            'password = "helloworld"',
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
            ('password = "xK9$mQ2vLp8#nR4z"', "Hardcoded password"),
            ('api_key = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"', "Hardcoded API key"),
            ('secret_key = "kJ8vQz3mN9pL2wXyRb5cDf7g"', "Hardcoded secret key"),
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
            'password = "xK9$MQ2vLp8#nR4z"',
            # Incidental <..> punctuation inside a random value is not an
            # angle-bracket placeholder.
            'password = "k<9x>Km2#pQzW4vT"',
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

    def test_structured_tokens_not_entropy_gated(self, temp_dir):
        """High-confidence token formats fire even for low-entropy bodies."""
        (temp_dir / "CLAUDE.md").write_text("Use token ghp_" + "a" * 40 + "\n")
        context = RepositoryContext(temp_dir)
        violations = ContentEmbeddedSecretsRule().check(context)
        assert len(violations) >= 1
        assert "GitHub personal access token" in violations[0].message

    def test_entropy_threshold_configurable(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            'Config: api_key = "9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c"\n'
        )
        context = RepositoryContext(temp_dir)
        # Raising the threshold above the value's entropy suppresses it
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": 5.0})
        assert rule.check(context) == []
        # Lowering it lets low-entropy values through
        (temp_dir / "CLAUDE.md").write_text('Config: api_key = "abababababababab"\n')
        context = RepositoryContext(temp_dir)
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": 0.5})
        assert len(rule.check(context)) == 1

    def test_entropy_threshold_invalid_config_uses_default(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text('Config: password = "hunter2placeholder"\n')
        context = RepositoryContext(temp_dir)
        rule = ContentEmbeddedSecretsRule({"entropy-threshold": "nonsense"})
        assert rule.check(context) == []

    def test_additional_placeholders_configurable(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text('Config: api_key = "staging-key-9f8a7b6c5d4e3f2a"\n')
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
