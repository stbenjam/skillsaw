"""
Tests for Cursor .mdc rules validation and legacy .cursorrules deprecation
"""

import pytest
from pathlib import Path

from skillsaw.rules.builtin.cursor import (
    CursorMdcValidRule,
    CursorRulesDeprecatedRule,
    CursorMdcFrontmatterRule,
    CursorActivationTypeRule,
    CursorCrlfDetectionRule,
    CursorGlobValidRule,
    CursorEmptyBodyRule,
    CursorDescriptionQualityRule,
    CursorGlobOverlapRule,
    CursorRuleSizeRule,
    CursorFrontmatterTypesRule,
    CursorDuplicateRulesRule,
    CursorAlwaysApplyOveruseRule,
)
from skillsaw.rule import Severity, AutofixConfidence
from skillsaw.context import RepositoryContext


@pytest.fixture
def repo_with_cursor_rules(temp_dir):
    """Create a repo with .cursor/rules/ directory"""
    cursor_dir = temp_dir / ".cursor"
    cursor_dir.mkdir()
    rules_dir = cursor_dir / "rules"
    rules_dir.mkdir()
    return temp_dir


def _write_mdc(temp_dir, name, content, subdir=None):
    """Helper to write a .mdc file in .cursor/rules/"""
    rules_dir = temp_dir / ".cursor" / "rules"
    if subdir:
        rules_dir = rules_dir / subdir
        rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / name
    path.write_text(content)
    return path


def _write_mdc_bytes(temp_dir, name, data):
    """Helper to write raw bytes to a .mdc file in .cursor/rules/"""
    rules_dir = temp_dir / ".cursor" / "rules"
    path = rules_dir / name
    path.write_bytes(data)
    return path


# --- CursorMdcValidRule tests ---


class TestCursorMdcValid:
    def test_valid_always_apply_rule(self, repo_with_cursor_rules):
        content = (
            "---\n"
            "description: Code style guidelines\n"
            "alwaysApply: true\n"
            "---\n\n"
            "# Code Style\n\n"
            "Use consistent formatting.\n"
        )
        _write_mdc(repo_with_cursor_rules, "code-style.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_valid_auto_attach_rule(self, repo_with_cursor_rules):
        content = (
            "---\n"
            "description: TypeScript conventions\n"
            "globs: src/**/*.ts, src/**/*.tsx\n"
            "alwaysApply: false\n"
            "---\n\n"
            "# TypeScript Rules\n"
        )
        _write_mdc(repo_with_cursor_rules, "typescript.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_valid_agent_rule(self, repo_with_cursor_rules):
        content = (
            "---\n"
            "description: Database migration guidelines\n"
            "---\n\n"
            "# Database Migrations\n"
        )
        _write_mdc(repo_with_cursor_rules, "db-migrations.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_valid_minimal_frontmatter(self, repo_with_cursor_rules):
        content = "---\nalwaysApply: true\n---\n\nDo something.\n"
        _write_mdc(repo_with_cursor_rules, "minimal.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_no_cursor_rules_dir(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_empty_cursor_rules_dir(self, repo_with_cursor_rules):
        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_non_mdc_file_warns(self, repo_with_cursor_rules):
        _write_mdc(repo_with_cursor_rules, "notes.txt", "some notes")

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "Non-.mdc" in violations[0].message
        assert "notes.txt" in violations[0].message

    def test_empty_mdc_file_warns(self, repo_with_cursor_rules):
        _write_mdc(repo_with_cursor_rules, "empty.mdc", "")

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "Empty" in violations[0].message

    def test_whitespace_only_mdc_warns(self, repo_with_cursor_rules):
        _write_mdc(repo_with_cursor_rules, "blank.mdc", "   \n\n  \n")

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Empty" in violations[0].message

    def test_missing_frontmatter_warns(self, repo_with_cursor_rules):
        content = "# Just Markdown\n\nNo frontmatter here.\n"
        _write_mdc(repo_with_cursor_rules, "no-fm.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "Missing frontmatter" in violations[0].message

    def test_invalid_yaml_frontmatter(self, repo_with_cursor_rules):
        content = "---\ndescription: [unclosed\n---\n\n# Bad YAML\n"
        _write_mdc(repo_with_cursor_rules, "bad-yaml.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert "Invalid YAML" in violations[0].message

    def test_unterminated_frontmatter(self, repo_with_cursor_rules):
        content = "---\ndescription: test\nThis never closes\n"
        _write_mdc(repo_with_cursor_rules, "open.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Unterminated frontmatter" in violations[0].message

    def test_frontmatter_not_a_mapping(self, repo_with_cursor_rules):
        content = "---\n- item1\n- item2\n---\n\n# List\n"
        _write_mdc(repo_with_cursor_rules, "list.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "must be a YAML mapping" in violations[0].message

    def test_unknown_frontmatter_key_warns(self, repo_with_cursor_rules):
        content = "---\n" "description: test\n" "priority: 5\n" "---\n\n" "# Rules\n"
        _write_mdc(repo_with_cursor_rules, "unknown-key.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "priority" in violations[0].message
        assert violations[0].line == 3

    def test_description_not_string(self, repo_with_cursor_rules):
        content = "---\ndescription: 42\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "bad-desc.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("must be a string" in v.message and "int" in v.message for v in violations)

    def test_description_empty_warns(self, repo_with_cursor_rules):
        content = "---\ndescription: ''\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "empty-desc.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("'description' is empty" in v.message for v in violations)

    def test_globs_as_list_passes(self, repo_with_cursor_rules):
        content = "---\nglobs:\n  - '*.ts'\n  - '*.tsx'\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "globs-list.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_globs_invalid_type(self, repo_with_cursor_rules):
        content = "---\nglobs: 42\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "globs-int.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("must be a string or list" in v.message for v in violations)

    def test_globs_empty_warns(self, repo_with_cursor_rules):
        content = "---\nglobs: ''\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "empty-globs.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any(
            "'globs' is empty" in v.message or "empty glob" in v.message.lower() for v in violations
        )

    def test_globs_trailing_comma_warns(self, repo_with_cursor_rules):
        content = "---\nglobs: '*.ts, *.tsx,'\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "trailing-comma.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Empty glob pattern" in violations[0].message

    def test_always_apply_not_bool(self, repo_with_cursor_rules):
        content = "---\nalwaysApply: 1\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "bad-bool.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("must be a boolean" in v.message for v in violations)

    def test_always_apply_string_true(self, repo_with_cursor_rules):
        content = '---\nalwaysApply: "true"\n---\n\n# Rules\n'
        _write_mdc(repo_with_cursor_rules, "string-bool.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("must be a boolean" in v.message for v in violations)

    def test_multiple_valid_mdc_files(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\ndescription: Rule A\nalwaysApply: true\n---\n\nA\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            "---\ndescription: Rule B\nglobs: '*.py'\n---\n\nB\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_multiple_errors(self, repo_with_cursor_rules):
        content = (
            "---\n" "description: 42\n" "globs: 123\n" "alwaysApply: 1\n" "---\n\n" "# Rules\n"
        )
        _write_mdc(repo_with_cursor_rules, "multi-bad.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) >= 3

    def test_mdc_in_subdirectory(self, repo_with_cursor_rules):
        content = "---\ndescription: Nested rule\nalwaysApply: false\n---\n\n# Nested\n"
        _write_mdc(repo_with_cursor_rules, "nested.mdc", content, subdir="category")

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_empty_frontmatter_block(self, repo_with_cursor_rules):
        content = "---\n---\n\n# Empty frontmatter\n"
        _write_mdc(repo_with_cursor_rules, "empty-fm.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("activation method" in v.message.lower() for v in violations)

    def test_rule_metadata(self):
        rule = CursorMdcValidRule()
        assert rule.rule_id == "cursor-mdc-valid"
        assert "mdc" in rule.description.lower()
        assert rule.default_severity() == Severity.ERROR

    def test_valid_single_glob(self, repo_with_cursor_rules):
        content = "---\nglobs: '**/*.py'\n---\n\n# Python Rules\n"
        _write_mdc(repo_with_cursor_rules, "python.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_no_activation_method_warns(self, repo_with_cursor_rules):
        content = "---\nalwaysApply: false\n---\n\n# Orphan rule\nNever activates.\n"
        _write_mdc(repo_with_cursor_rules, "orphan.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("activation method" in v.message.lower() for v in violations)

    def test_empty_frontmatter_no_activation_warns(self, repo_with_cursor_rules):
        content = "---\n---\n\n# Empty frontmatter\nContent here.\n"
        _write_mdc(repo_with_cursor_rules, "empty-fm-body.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("activation method" in v.message.lower() for v in violations)

    def test_frontmatter_but_no_body_warns(self, repo_with_cursor_rules):
        content = "---\ndescription: Empty body rule\nalwaysApply: true\n---\n"
        _write_mdc(repo_with_cursor_rules, "no-body.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("no content body" in v.message.lower() for v in violations)

    def test_globs_list_with_non_string_element(self, repo_with_cursor_rules):
        content = "---\nglobs:\n  - '*.ts'\n  - 42\n---\n\n# Rules\n"
        _write_mdc(repo_with_cursor_rules, "bad-list-glob.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcValidRule()
        violations = rule.check(context)
        assert any("must be a string or list" in v.message for v in violations)


# --- CursorRulesDeprecatedRule tests ---


class TestCursorRulesDeprecated:
    def test_no_cursorrules_file(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = CursorRulesDeprecatedRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_cursorrules_present(self, temp_dir):
        (temp_dir / ".cursorrules").write_text("You are a helpful assistant.\n")

        context = RepositoryContext(temp_dir)
        rule = CursorRulesDeprecatedRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "deprecated" in violations[0].message.lower()
        assert ".cursor/rules/" in violations[0].message

    def test_empty_cursorrules(self, temp_dir):
        (temp_dir / ".cursorrules").write_text("")

        context = RepositoryContext(temp_dir)
        rule = CursorRulesDeprecatedRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_rule_metadata(self):
        rule = CursorRulesDeprecatedRule()
        assert rule.rule_id == "cursor-rules-deprecated"
        assert "deprecated" in rule.description.lower()
        assert rule.default_severity() == Severity.WARNING

    def test_both_cursorrules_and_mdc(self, repo_with_cursor_rules):
        (repo_with_cursor_rules / ".cursorrules").write_text("Legacy rules here.\n")
        _write_mdc(
            repo_with_cursor_rules,
            "new.mdc",
            "---\ndescription: New rule\nalwaysApply: true\n---\n\n# New\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)

        mdc_rule = CursorMdcValidRule()
        mdc_violations = mdc_rule.check(context)
        assert len(mdc_violations) == 0

        deprecated_rule = CursorRulesDeprecatedRule()
        dep_violations = deprecated_rule.check(context)
        assert len(dep_violations) == 1
        assert "deprecated" in dep_violations[0].message.lower()

    def test_autofix_generates_mdc(self, repo_with_cursor_rules):
        (repo_with_cursor_rules / ".cursorrules").write_text(
            "You are a helpful coding assistant.\n"
        )
        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorRulesDeprecatedRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert "migrated-cursorrules.mdc" in str(fixes[0].file_path)
        assert "alwaysApply: true" in fixes[0].fixed_content
        assert "You are a helpful coding assistant." in fixes[0].fixed_content

    def test_autofix_skips_empty(self, temp_dir):
        (temp_dir / ".cursorrules").write_text("")
        context = RepositoryContext(temp_dir)
        rule = CursorRulesDeprecatedRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 0

    def test_supports_autofix(self):
        rule = CursorRulesDeprecatedRule()
        assert rule.supports_autofix


# --- CursorMdcFrontmatterRule tests ---


class TestCursorMdcFrontmatter:
    def test_valid_keys_pass(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nglobs: '*.py'\nalwaysApply: false\n---\n\n# Body\n"
        _write_mdc(repo_with_cursor_rules, "good.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_unknown_key_flagged(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\npriority: 5\n---\n\n# Body\n"
        _write_mdc(repo_with_cursor_rules, "bad.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "priority" in violations[0].message
        assert "silently ignored" in violations[0].message

    def test_multiple_unknown_keys(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\npriority: 5\nauthor: me\n---\n\n# Body\n"
        _write_mdc(repo_with_cursor_rules, "multi-bad.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert len(violations) == 2

    def test_no_cursor_dir(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_skips_invalid_frontmatter(self, repo_with_cursor_rules):
        content = "---\ndescription: [unclosed\n---\n\n# Bad\n"
        _write_mdc(repo_with_cursor_rules, "bad-yaml.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_line_number_reported(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\npriority: 5\n---\n\n# Body\n"
        _write_mdc(repo_with_cursor_rules, "line.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        assert violations[0].line == 3

    def test_autofix_removes_unknown_keys(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\npriority: 5\nauthor: me\n---\n\n# Body\n"
        _write_mdc(repo_with_cursor_rules, "fix-me.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorMdcFrontmatterRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "priority" not in fixes[0].fixed_content
        assert "author" not in fixes[0].fixed_content
        assert "description: Test" in fixes[0].fixed_content
        assert fixes[0].fixed_content.startswith("---\n")
        assert "# Body" in fixes[0].fixed_content

    def test_rule_metadata(self):
        rule = CursorMdcFrontmatterRule()
        assert rule.rule_id == "cursor-mdc-frontmatter"
        assert rule.supports_autofix


# --- CursorActivationTypeRule tests ---


class TestCursorActivationType:
    def test_always_apply_passes(self, repo_with_cursor_rules):
        content = "---\nalwaysApply: true\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "always.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_glob_activation_passes(self, repo_with_cursor_rules):
        content = "---\nglobs: '*.py'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "glob.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_agent_requested_passes(self, repo_with_cursor_rules):
        content = "---\ndescription: Use this for Python code reviews\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "agent.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_manual_no_frontmatter_warns(self, repo_with_cursor_rules):
        content = "# Just a rule\n\nNo frontmatter.\n"
        _write_mdc(repo_with_cursor_rules, "manual.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Manual activation" in violations[0].message

    def test_manual_empty_frontmatter_warns(self, repo_with_cursor_rules):
        content = "---\n---\n\n# Empty frontmatter rule\n"
        _write_mdc(repo_with_cursor_rules, "empty-fm.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Manual" in violations[0].message

    def test_skips_parse_errors(self, repo_with_cursor_rules):
        content = "---\ndescription: [unclosed\n---\n\n# Bad\n"
        _write_mdc(repo_with_cursor_rules, "bad.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorActivationTypeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorActivationTypeRule()
        assert rule.rule_id == "cursor-activation-type"
        assert not rule.supports_autofix


# --- CursorCrlfDetectionRule tests ---


class TestCursorCrlfDetection:
    def test_lf_passes(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "lf.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorCrlfDetectionRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_crlf_flagged(self, repo_with_cursor_rules):
        _write_mdc_bytes(
            repo_with_cursor_rules,
            "crlf.mdc",
            b"---\r\ndescription: Test\r\n---\r\n\r\n# Rule\r\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorCrlfDetectionRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "CRLF" in violations[0].message

    def test_autofix_converts_to_lf(self, repo_with_cursor_rules):
        _write_mdc_bytes(
            repo_with_cursor_rules,
            "crlf.mdc",
            b"---\r\ndescription: Test\r\n---\r\n\r\n# Rule\r\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorCrlfDetectionRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SAFE
        assert "\r\n" not in fixes[0].fixed_content
        assert "---\ndescription: Test\n---\n" in fixes[0].fixed_content

    def test_no_cursor_dir(self, temp_dir):
        context = RepositoryContext(temp_dir)
        rule = CursorCrlfDetectionRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorCrlfDetectionRule()
        assert rule.rule_id == "cursor-crlf-detection"
        assert rule.supports_autofix
        assert rule.default_severity() == Severity.ERROR


# --- CursorGlobValidRule tests ---


class TestCursorGlobValid:
    def test_valid_glob_passes(self, repo_with_cursor_rules):
        content = "---\nglobs: '**/*.py'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "good.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_overly_broad_glob_warns(self, repo_with_cursor_rules):
        content = "---\nglobs: '*'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "broad.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Overly broad" in violations[0].message

    def test_star_star_slash_star_warns(self, repo_with_cursor_rules):
        content = "---\nglobs: '**/*'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "broadest.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Overly broad" in violations[0].message

    def test_unmatched_bracket_error(self, repo_with_cursor_rules):
        content = "---\nglobs: 'src/[unclosed'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "bad-bracket.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobValidRule()
        violations = rule.check(context)
        assert any("invalid syntax" in v.message.lower() for v in violations)

    def test_no_globs_skipped(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "no-globs.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobValidRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorGlobValidRule()
        assert rule.rule_id == "cursor-glob-valid"
        assert not rule.supports_autofix


# --- CursorEmptyBodyRule tests ---


class TestCursorEmptyBody:
    def test_rule_with_body_passes(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n\n# Rule\n\nContent here.\n"
        _write_mdc(repo_with_cursor_rules, "good.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorEmptyBodyRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_empty_body_flagged(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n"
        _write_mdc(repo_with_cursor_rules, "empty.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorEmptyBodyRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "no content body" in violations[0].message.lower()

    def test_whitespace_only_body_flagged(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n   \n\n  \n"
        _write_mdc(repo_with_cursor_rules, "ws-body.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorEmptyBodyRule()
        violations = rule.check(context)
        assert len(violations) == 1

    def test_autofix_suggests_template(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n"
        _write_mdc(repo_with_cursor_rules, "empty.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorEmptyBodyRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert "TODO" in fixes[0].fixed_content

    def test_no_frontmatter_skipped(self, repo_with_cursor_rules):
        content = "# Just body\n"
        _write_mdc(repo_with_cursor_rules, "no-fm.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorEmptyBodyRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorEmptyBodyRule()
        assert rule.rule_id == "cursor-empty-body"
        assert rule.supports_autofix


# --- CursorDescriptionQualityRule tests ---


class TestCursorDescriptionQuality:
    def test_good_description_passes(self, repo_with_cursor_rules):
        content = (
            "---\ndescription: Python code review guidelines for async functions\n---\n\n# Rule\n"
        )
        _write_mdc(repo_with_cursor_rules, "good.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_short_description_warns(self, repo_with_cursor_rules):
        content = "---\ndescription: Help\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "short.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "too short" in violations[0].message.lower()

    def test_vague_description_warns(self, repo_with_cursor_rules):
        content = "---\ndescription: General stuff for various things\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "vague.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        assert any("vague" in v.message.lower() for v in violations)

    def test_skips_always_apply_rules(self, repo_with_cursor_rules):
        content = "---\ndescription: x\nalwaysApply: true\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "always.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_skips_glob_rules(self, repo_with_cursor_rules):
        content = "---\ndescription: x\nglobs: '*.py'\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "glob.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_empty_description_on_agent_warns(self, repo_with_cursor_rules):
        content = "---\ndescription: ''\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "empty-desc.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDescriptionQualityRule()
        violations = rule.check(context)
        # Empty description means manual activation, not agent-requested, so no violation
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorDescriptionQualityRule()
        assert rule.rule_id == "cursor-description-quality"
        assert not rule.supports_autofix


# --- CursorGlobOverlapRule tests ---


class TestCursorGlobOverlap:
    def test_no_overlap_passes(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "py.mdc",
            "---\nglobs: '*.py'\n---\n\n# Python\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "ts.mdc",
            "---\nglobs: '*.ts'\n---\n\n# TypeScript\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobOverlapRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_overlap_flagged(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "py1.mdc",
            "---\nglobs: '*.py'\n---\n\n# Python 1\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "py2.mdc",
            "---\nglobs: '*.py'\n---\n\n# Python 2\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobOverlapRule()
        violations = rule.check(context)
        assert len(violations) == 2
        assert any("also used by" in v.message for v in violations)

    def test_partial_overlap_from_list(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\nglobs:\n  - '*.py'\n  - '*.ts'\n---\n\n# A\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            "---\nglobs: '*.py'\n---\n\n# B\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobOverlapRule()
        violations = rule.check(context)
        assert any("*.py" in v.message for v in violations)

    def test_no_globs_skipped(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\ndescription: A\nalwaysApply: true\n---\n\n# A\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorGlobOverlapRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorGlobOverlapRule()
        assert rule.rule_id == "cursor-glob-overlap"
        assert not rule.supports_autofix


# --- CursorRuleSizeRule tests ---


class TestCursorRuleSize:
    def test_small_file_passes(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nalwaysApply: true\n---\n\n# Small rule\n"
        _write_mdc(repo_with_cursor_rules, "small.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorRuleSizeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_large_file_warns(self, repo_with_cursor_rules):
        lines = ["---", "description: Big rule", "alwaysApply: true", "---", ""]
        lines.extend([f"Line {i}" for i in range(600)])
        content = "\n".join(lines) + "\n"
        _write_mdc(repo_with_cursor_rules, "large.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorRuleSizeRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "605" in violations[0].message
        assert "context budget" in violations[0].message.lower()

    def test_custom_max_lines(self, repo_with_cursor_rules):
        lines = ["---", "description: Test", "alwaysApply: true", "---", ""]
        lines.extend([f"Line {i}" for i in range(20)])
        content = "\n".join(lines) + "\n"
        _write_mdc(repo_with_cursor_rules, "medium.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorRuleSizeRule(config={"max-lines": 10})
        violations = rule.check(context)
        assert len(violations) == 1

    def test_exactly_at_limit_passes(self, repo_with_cursor_rules):
        lines = ["---", "description: Test", "alwaysApply: true", "---"]
        lines.extend([f"Line {i}" for i in range(496)])
        content = "\n".join(lines) + "\n"
        _write_mdc(repo_with_cursor_rules, "limit.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorRuleSizeRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorRuleSizeRule()
        assert rule.rule_id == "cursor-rule-size"
        assert not rule.supports_autofix


# --- CursorFrontmatterTypesRule tests ---


class TestCursorFrontmatterTypes:
    def test_correct_types_pass(self, repo_with_cursor_rules):
        content = "---\ndescription: Test\nglobs: '*.py'\nalwaysApply: true\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "good.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_always_apply_string_flagged(self, repo_with_cursor_rules):
        content = '---\nalwaysApply: "true"\n---\n\n# Rule\n'
        _write_mdc(repo_with_cursor_rules, "str-bool.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "boolean" in violations[0].message.lower()

    def test_always_apply_int_flagged(self, repo_with_cursor_rules):
        content = "---\nalwaysApply: 1\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "int-bool.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 1

    def test_globs_number_flagged(self, repo_with_cursor_rules):
        content = "---\nglobs: 42\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "num-glob.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "globs" in violations[0].message

    def test_globs_list_with_non_string_flagged(self, repo_with_cursor_rules):
        content = "---\nglobs:\n  - '*.py'\n  - 42\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "mixed-list.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "strings" in violations[0].message

    def test_description_not_string_flagged(self, repo_with_cursor_rules):
        content = "---\ndescription: 42\n---\n\n# Rule\n"
        _write_mdc(repo_with_cursor_rules, "num-desc.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "description" in violations[0].message

    def test_autofix_coerces_bool(self, repo_with_cursor_rules):
        content = '---\nalwaysApply: "true"\n---\n\n# Rule\n'
        _write_mdc(repo_with_cursor_rules, "fix-bool.mdc", content)

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorFrontmatterTypesRule()
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert "alwaysApply: true" in fixes[0].fixed_content
        assert '"true"' not in fixes[0].fixed_content

    def test_rule_metadata(self):
        rule = CursorFrontmatterTypesRule()
        assert rule.rule_id == "cursor-frontmatter-types"
        assert rule.supports_autofix
        assert rule.default_severity() == Severity.ERROR


# --- CursorDuplicateRulesRule tests ---


class TestCursorDuplicateRules:
    def test_unique_rules_pass(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\ndescription: A\nalwaysApply: true\n---\n\n# Alpha\n\nCompletely unique content for rule A.\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            "---\ndescription: B\nalwaysApply: true\n---\n\n# Beta\n\nTotally different content for rule B.\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDuplicateRulesRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_duplicate_bodies_flagged(self, repo_with_cursor_rules):
        body = "\n# Shared Rule\n\nUse consistent formatting.\nFollow the style guide.\n"
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            f"---\ndescription: A\nalwaysApply: true\n---\n{body}",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            f"---\ndescription: B\nalwaysApply: true\n---\n{body}",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDuplicateRulesRule()
        violations = rule.check(context)
        assert len(violations) >= 1
        assert "similar" in violations[0].message.lower()

    def test_custom_threshold(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\ndescription: A\nalwaysApply: true\n---\n\n# Rule\n\nSome content here.\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            "---\ndescription: B\nalwaysApply: true\n---\n\n# Rule\n\nSome content here, slightly different.\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDuplicateRulesRule(config={"similarity-threshold": 0.5})
        violations = rule.check(context)
        assert len(violations) >= 1

    def test_empty_bodies_not_flagged(self, repo_with_cursor_rules):
        _write_mdc(
            repo_with_cursor_rules,
            "a.mdc",
            "---\ndescription: A\nalwaysApply: true\n---\n",
        )
        _write_mdc(
            repo_with_cursor_rules,
            "b.mdc",
            "---\ndescription: B\nalwaysApply: true\n---\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorDuplicateRulesRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_rule_metadata(self):
        rule = CursorDuplicateRulesRule()
        assert rule.rule_id == "cursor-duplicate-rules"
        assert not rule.supports_autofix


# --- CursorAlwaysApplyOveruseRule tests ---


class TestCursorAlwaysApplyOveruse:
    def test_few_always_apply_passes(self, repo_with_cursor_rules):
        for i in range(3):
            _write_mdc(
                repo_with_cursor_rules,
                f"rule{i}.mdc",
                f"---\ndescription: Rule {i}\nalwaysApply: true\n---\n\n# Rule {i}\n",
            )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorAlwaysApplyOveruseRule()
        violations = rule.check(context)
        assert len(violations) == 0

    def test_too_many_always_apply_warns(self, repo_with_cursor_rules):
        for i in range(5):
            _write_mdc(
                repo_with_cursor_rules,
                f"rule{i}.mdc",
                f"---\ndescription: Rule {i}\nalwaysApply: true\n---\n\n# Rule {i}\n",
            )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorAlwaysApplyOveruseRule()
        violations = rule.check(context)
        assert len(violations) == 5
        assert "5 rules" in violations[0].message
        assert "context budget" in violations[0].message.lower()

    def test_mixed_activation_counted_correctly(self, repo_with_cursor_rules):
        for i in range(4):
            _write_mdc(
                repo_with_cursor_rules,
                f"always{i}.mdc",
                f"---\ndescription: Always {i}\nalwaysApply: true\n---\n\n# A {i}\n",
            )
        _write_mdc(
            repo_with_cursor_rules,
            "glob.mdc",
            "---\nglobs: '*.py'\n---\n\n# Glob rule\n",
        )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorAlwaysApplyOveruseRule()
        violations = rule.check(context)
        assert len(violations) == 4

    def test_custom_max(self, repo_with_cursor_rules):
        for i in range(2):
            _write_mdc(
                repo_with_cursor_rules,
                f"rule{i}.mdc",
                f"---\ndescription: Rule {i}\nalwaysApply: true\n---\n\n# Rule {i}\n",
            )

        context = RepositoryContext(repo_with_cursor_rules)
        rule = CursorAlwaysApplyOveruseRule(config={"max-always-apply": 1})
        violations = rule.check(context)
        assert len(violations) == 2

    def test_rule_metadata(self):
        rule = CursorAlwaysApplyOveruseRule()
        assert rule.rule_id == "cursor-always-apply-overuse"
        assert not rule.supports_autofix
