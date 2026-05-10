"""
Tests for .claude/rules/ directory validation
"""

import pytest
from pathlib import Path

from skillsaw.rules.builtin.rules_dir import RulesValidRule
from skillsaw.rule import Severity
from skillsaw.context import RepositoryContext, RepositoryType


@pytest.fixture
def dot_claude_with_rules(temp_dir):
    """Create a DOT_CLAUDE repo with a rules/ directory"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    rules_dir = claude_dir / "rules"
    rules_dir.mkdir()
    return temp_dir


def _write_rule(temp_dir, name, content, subdir=None):
    """Helper to write a rule file in .claude/rules/"""
    rules_dir = temp_dir / ".claude" / "rules"
    if subdir:
        rules_dir = rules_dir / subdir
        rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / name
    path.write_text(content)
    return path


def test_valid_rule_no_frontmatter(dot_claude_with_rules):
    """Rule file without frontmatter is valid"""
    _write_rule(
        dot_claude_with_rules, "code-style.md", "# Code Style\n\nUse 2-space indentation.\n"
    )

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_rule_with_paths(dot_claude_with_rules):
    """Rule file with valid paths frontmatter passes"""
    content = '---\npaths:\n  - "src/**/*.ts"\n  - "lib/**/*.ts"\n---\n\n# TypeScript Rules\n'
    _write_rule(dot_claude_with_rules, "typescript.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_rule_with_brace_expansion(dot_claude_with_rules):
    """Brace expansion glob patterns are valid"""
    content = '---\npaths:\n  - "src/**/*.{ts,tsx}"\n---\n\n# Frontend Rules\n'
    _write_rule(dot_claude_with_rules, "frontend.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_rule_in_subdirectory(dot_claude_with_rules):
    """Rules in subdirectories are discovered and validated"""
    content = "# Backend Rules\n\nUse structured logging.\n"
    _write_rule(dot_claude_with_rules, "logging.md", content, subdir="backend")

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_non_markdown_file_warns(dot_claude_with_rules):
    """Non-markdown files in rules/ produce a warning"""
    _write_rule(dot_claude_with_rules, "notes.txt", "some notes")

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING
    assert "Non-markdown" in violations[0].message
    assert "notes.txt" in violations[0].message


def test_invalid_yaml_frontmatter(dot_claude_with_rules):
    """Invalid YAML in frontmatter produces an error"""
    content = "---\npaths: [unclosed\n---\n\n# Bad YAML\n"
    _write_rule(dot_claude_with_rules, "bad.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.ERROR
    assert "Invalid YAML" in violations[0].message


def test_unterminated_frontmatter(dot_claude_with_rules):
    """Frontmatter without closing --- produces an error"""
    content = "---\npaths:\n  - '**/*.ts'\nThis never closes\n"
    _write_rule(dot_claude_with_rules, "open.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Unterminated frontmatter" in violations[0].message


def test_frontmatter_not_a_mapping(dot_claude_with_rules):
    """Frontmatter that isn't a mapping produces an error"""
    content = "---\n- item1\n- item2\n---\n\n# List frontmatter\n"
    _write_rule(dot_claude_with_rules, "list.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "must be a YAML mapping" in violations[0].message


def test_unknown_frontmatter_key_warns(dot_claude_with_rules):
    """Unknown frontmatter keys produce a warning with correct line number"""
    content = "---\npaths:\n  - '**/*.ts'\ntitle: My Rule\n---\n\n# Rules\n"
    _write_rule(dot_claude_with_rules, "extra.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING
    assert "title" in violations[0].message
    assert violations[0].line == 4


def test_paths_not_a_list(dot_claude_with_rules):
    """paths field that isn't a list produces an error with line number"""
    content = '---\npaths: "**/*.ts"\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "scalar.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "must be a list" in violations[0].message
    assert violations[0].line == 2


def test_paths_entry_not_string(dot_claude_with_rules):
    """Non-string entry in paths list produces an error"""
    content = "---\npaths:\n  - 42\n---\n\n# Rules\n"
    _write_rule(dot_claude_with_rules, "number.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "must be a string" in violations[0].message
    assert "int" in violations[0].message


def test_empty_glob_pattern(dot_claude_with_rules):
    """Empty glob pattern produces an error"""
    content = '---\npaths:\n  - ""\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "empty.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "empty glob pattern" in violations[0].message


def test_absolute_path_pattern(dot_claude_with_rules):
    """Absolute path in pattern produces an error with paths line number"""
    content = '---\npaths:\n  - "/etc/config/**"\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "absolute.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "relative path" in violations[0].message
    assert violations[0].line == 2


def test_parent_traversal_pattern(dot_claude_with_rules):
    """Pattern with .. segments produces an error"""
    content = '---\npaths:\n  - "../other-project/**/*.ts"\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "escape.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "must not contain '..'" in violations[0].message


def test_no_rules_directory(temp_dir):
    """DOT_CLAUDE repo without rules/ directory produces no violations"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_empty_rules_directory(dot_claude_with_rules):
    """Empty rules/ directory produces no violations"""
    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_multiple_valid_patterns(dot_claude_with_rules):
    """Multiple valid glob patterns all pass"""
    content = (
        "---\n"
        "paths:\n"
        '  - "**/*.ts"\n'
        '  - "src/**/*"\n'
        '  - "*.md"\n'
        '  - "src/components/*.tsx"\n'
        '  - "src/**/*.{ts,tsx}"\n'
        '  - "lib/**/*.ts"\n'
        '  - "tests/**/*.test.ts"\n'
        "---\n\n# Rules\n"
    )
    _write_rule(dot_claude_with_rules, "all-patterns.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_multiple_errors_reported(dot_claude_with_rules):
    """Multiple invalid entries each produce their own violation"""
    content = '---\npaths:\n  - 42\n  - ""\n  - /absolute\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "multi-bad.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 3


def test_empty_frontmatter_is_valid(dot_claude_with_rules):
    """Frontmatter block with no keys is valid"""
    content = "---\n---\n\n# Empty frontmatter\n"
    _write_rule(dot_claude_with_rules, "empty-fm.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_frontmatter_with_dashes_in_value(dot_claude_with_rules):
    """Frontmatter with --- inside a YAML value must not truncate parsing"""
    content = '---\npaths:\n  - "src/---internal/**/*.ts"\n---\n\n# Rules\n'
    _write_rule(dot_claude_with_rules, "dashes.md", content)

    context = RepositoryContext(dot_claude_with_rules)
    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_rule_metadata():
    """Verify rule ID, description, and default severity"""
    rule = RulesValidRule()
    assert rule.rule_id == "rules-valid"
    assert "rules/" in rule.description
    assert rule.default_severity() == Severity.ERROR


def test_auto_enabled_for_dot_claude(dot_claude_with_rules):
    """Rule should be auto-enabled for DOT_CLAUDE repos"""
    from skillsaw.config import LinterConfig

    context = RepositoryContext(dot_claude_with_rules)
    assert context.repo_type == RepositoryType.DOT_CLAUDE

    config = LinterConfig.default()
    assert config.is_rule_enabled("rules-valid", context, RulesValidRule.repo_types) is True


def test_auto_disabled_for_non_dot_claude(valid_plugin):
    """Rule should not be auto-enabled for non-DOT_CLAUDE repos"""
    from skillsaw.config import LinterConfig

    context = RepositoryContext(valid_plugin)
    assert context.repo_type == RepositoryType.SINGLE_PLUGIN

    config = LinterConfig.default()
    assert config.is_rule_enabled("rules-valid", context, RulesValidRule.repo_types) is False


def test_linting_dot_claude_directly(temp_dir):
    """When linting .claude/ directly, rules/ is found correctly"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    rules_dir = claude_dir / "rules"
    rules_dir.mkdir()
    (rules_dir / "notes.txt").write_text("not markdown")

    context = RepositoryContext(claude_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE

    rule = RulesValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Non-markdown" in violations[0].message
