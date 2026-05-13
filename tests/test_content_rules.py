"""Tests for content intelligence rules."""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
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
        content = "Line 1\nLine 2\nPassword: password='supersecretpassword123'\nLine 4\n"
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
