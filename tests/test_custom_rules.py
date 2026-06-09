"""
Tests for custom rule loading functionality
"""

import json
import shutil

import pytest
from pathlib import Path

from skillsaw.linter import Linter
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig, find_config
from skillsaw.rules.builtin.utils import invalidate_read_caches

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(src, dst)
    return dst


def test_load_valid_custom_rule(valid_plugin, temp_dir):
    """Test that a valid custom rule loads successfully"""
    # Create a valid custom rule file
    custom_rule_file = temp_dir / "custom_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class TestCustomRule(Rule):
    @property
    def rule_id(self) -> str:
        return "test-custom-rule"

    @property
    def description(self) -> str:
        return "A test custom rule"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    # Create config with custom rule
    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    # Should load without error
    linter = Linter(context, config)

    # Verify the custom rule was loaded
    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "test-custom-rule" in rule_ids


def test_load_custom_rule_missing_file(valid_plugin):
    """Test that linter fails when custom rule file doesn't exist"""
    config = LinterConfig(custom_rules=["nonexistent_rule.py"])
    context = RepositoryContext(valid_plugin)

    # Should raise FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Custom rule file not found"):
        Linter(context, config)


def test_load_custom_rule_import_error(valid_plugin, temp_dir):
    """Test that linter fails when custom rule has import errors"""
    # Create a custom rule file with import error
    custom_rule_file = temp_dir / "bad_import_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from nonexistent_module import something  # This will cause ImportError
from typing import List

class BadImportRule(Rule):
    @property
    def rule_id(self) -> str:
        return "bad-import-rule"

    @property
    def description(self) -> str:
        return "A rule with bad import"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    # Should raise ModuleNotFoundError or ImportError
    with pytest.raises((ModuleNotFoundError, ImportError)):
        Linter(context, config)


def test_load_custom_rule_syntax_error(valid_plugin, temp_dir):
    """Test that linter fails when custom rule has syntax errors"""
    # Create a custom rule file with syntax error
    custom_rule_file = temp_dir / "syntax_error_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class SyntaxErrorRule(Rule):
    @property
    def rule_id(self) -> str:
        return "syntax-error-rule"

    @property
    def description(self) -> str
        return "Missing colon here"  # Syntax error - missing colon above

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    # Should raise SyntaxError
    with pytest.raises(SyntaxError):
        Linter(context, config)


def test_load_custom_rule_missing_imports(valid_plugin, temp_dir):
    """Test that linter fails when custom rule can't import from skillsaw"""
    # Create a custom rule file that tries to import a nonexistent class
    custom_rule_file = temp_dir / "missing_export_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, NonExistentClass  # NonExistentClass doesn't exist
from typing import List

class MissingExportRule(Rule):
    @property
    def rule_id(self) -> str:
        return "missing-export-rule"

    @property
    def description(self) -> str:
        return "A rule trying to import nonexistent class"

    def default_severity(self):
        from skillsaw import Severity
        return Severity.WARNING

    def check(self, context):
        return []
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    # Should raise ImportError
    with pytest.raises(ImportError, match="cannot import name 'NonExistentClass'"):
        Linter(context, config)


def test_load_custom_rule_relative_path(valid_plugin, temp_dir):
    """Test that custom rules with relative paths work correctly"""
    # Create a custom rule file in the plugin directory
    custom_rule_file = valid_plugin / "my_custom_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class RelativePathRule(Rule):
    @property
    def rule_id(self) -> str:
        return "relative-path-rule"

    @property
    def description(self) -> str:
        return "A rule loaded from relative path"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    # Use relative path (relative to config_dir which defaults to root_path)
    config = LinterConfig(custom_rules=["./my_custom_rule.py"])
    context = RepositoryContext(valid_plugin)

    # Should load successfully
    linter = Linter(context, config)

    # Verify the custom rule was loaded
    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "relative-path-rule" in rule_ids


def test_load_custom_rule_relative_to_config_dir(valid_plugin, temp_dir):
    """Test that relative custom rule paths resolve against config_dir, not root_path"""
    # Put the custom rule in the parent (config) directory, not the lint target
    config_dir = temp_dir / "config_parent"
    config_dir.mkdir()
    custom_rule_file = config_dir / "my_custom_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class ConfigDirRule(Rule):
    @property
    def rule_id(self) -> str:
        return "config-dir-rule"

    @property
    def description(self) -> str:
        return "A rule loaded relative to config dir"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    # config_dir differs from the lint target (valid_plugin)
    config = LinterConfig(custom_rules=["./my_custom_rule.py"], config_dir=config_dir)
    context = RepositoryContext(valid_plugin)

    linter = Linter(context, config)

    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "config-dir-rule" in rule_ids


def test_load_multiple_custom_rules(valid_plugin, temp_dir):
    """Test loading multiple custom rules at once"""
    # Create two custom rule files
    custom_rule_1 = temp_dir / "custom_rule_1.py"
    custom_rule_1.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class CustomRule1(Rule):
    @property
    def rule_id(self) -> str:
        return "custom-rule-1"

    @property
    def description(self) -> str:
        return "First custom rule"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    custom_rule_2 = temp_dir / "custom_rule_2.py"
    custom_rule_2.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class CustomRule2(Rule):
    @property
    def rule_id(self) -> str:
        return "custom-rule-2"

    @property
    def description(self) -> str:
        return "Second custom rule"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    # Create config with both custom rules
    config = LinterConfig(custom_rules=[str(custom_rule_1), str(custom_rule_2)])
    context = RepositoryContext(valid_plugin)

    # Should load both without error
    linter = Linter(context, config)

    # Verify both custom rules were loaded
    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "custom-rule-1" in rule_ids
    assert "custom-rule-2" in rule_ids


def test_custom_rule_can_find_violations(valid_plugin, temp_dir):
    """Test that custom rules can actually find and report violations"""
    # Create a custom rule that always finds a violation
    custom_rule_file = temp_dir / "violation_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class ViolationRule(Rule):
    @property
    def rule_id(self) -> str:
        return "always-violates"

    @property
    def description(self) -> str:
        return "A rule that always finds a violation"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("This is a test violation")]
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    linter = Linter(context, config)
    violations = linter.run()

    # Should find the violation
    assert len(violations) > 0
    assert any(v.rule_id == "always-violates" for v in violations)
    assert any("This is a test violation" in v.message for v in violations)


def test_custom_rule_respects_exclude_patterns(valid_plugin, temp_dir):
    """Test that exclude patterns filter violations from custom rules"""
    custom_rule_file = temp_dir / "file_rule.py"
    custom_rule_file.write_text("""
from pathlib import Path
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class FileRule(Rule):
    @property
    def rule_id(self) -> str:
        return "file-rule"

    @property
    def description(self) -> str:
        return "Reports a violation for every markdown file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for f in context.root_path.rglob("*.md"):
            violations.append(self.violation("Found file", file_path=f))
        return violations
""")

    # Create files in both excluded and non-excluded directories
    sub_dir = valid_plugin / "sub"
    sub_dir.mkdir()
    tmpl_dir = sub_dir / "templates"
    tmpl_dir.mkdir()
    (tmpl_dir / "TEMPLATE.md").write_text("# Template\n")
    (valid_plugin / "docs.md").write_text("# Docs\n")

    # Use default exclude patterns (which include **/templates/**)
    config = LinterConfig(
        custom_rules=[str(custom_rule_file)],
        exclude_patterns=["**/templates/**"],
    )
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, config)
    violations = linter.run()

    file_rule_violations = [v for v in violations if v.rule_id == "file-rule"]
    assert file_rule_violations, "Expected at least one file-rule violation"
    assert any(
        Path(v.file_path).name == "docs.md" for v in file_rule_violations
    ), "Non-excluded markdown file should still be reported"
    # TEMPLATE.md in templates/ should be excluded
    assert all(
        "templates" not in Path(v.file_path).parts for v in file_rule_violations
    ), "Excluded file was not filtered"


def test_custom_rule_respects_disabled_config(valid_plugin, temp_dir):
    """Test that custom rules respect the enabled/disabled config"""
    # Create a custom rule
    custom_rule_file = temp_dir / "disabled_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class DisabledRule(Rule):
    @property
    def rule_id(self) -> str:
        return "disabled-rule"

    @property
    def description(self) -> str:
        return "A rule that will be disabled"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("Should not see this")]
""")

    # Create config with custom rule disabled
    config = LinterConfig(
        custom_rules=[str(custom_rule_file)], rules={"disabled-rule": {"enabled": False}}
    )
    context = RepositoryContext(valid_plugin)

    linter = Linter(context, config)

    # Custom rule should not be loaded
    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "disabled-rule" not in rule_ids


def test_promptfoo_budget_example_fixture():
    """Test that the promptfoo-budget custom rule example works against its fixture."""
    fixture_dir = (
        Path(__file__).parent.parent / "examples" / "custom-rules" / "promptfoo" / "fixture"
    )
    rule_file = fixture_dir.parent / "promptfoo_budget_rule.py"
    assert fixture_dir.is_dir(), f"Fixture dir missing: {fixture_dir}"
    assert rule_file.is_file(), f"Rule file missing: {rule_file}"

    config = LinterConfig(
        custom_rules=[str(rule_file)],
        rules={"promptfoo-budget": {"enabled": True, "severity": "error"}},
    )
    context = RepositoryContext(fixture_dir)
    linter = Linter(context, config)
    violations = linter.run()

    budget_violations = [v for v in violations if v.rule_id == "promptfoo-budget"]
    errors = [v for v in budget_violations if v.severity.name == "ERROR"]
    warnings = [v for v in budget_violations if v.severity.name == "WARNING"]

    assert len(errors) == 2, f"Expected 2 errors, got {len(errors)}: {errors}"
    assert len(warnings) == 1, f"Expected 1 warning, got {len(warnings)}: {warnings}"

    assert any("judge-size" in v.message for v in errors)
    assert any("exceeds budget" in v.message for v in errors)
    assert any("over-classified" in v.message for v in warnings)


def test_custom_rule_tree_example_finds_violations(tmp_path):
    """Test the docs custom rule example: tree-based TODO detection."""
    fixture = copy_fixture("custom-rule-tree-example", tmp_path)
    rule_file = fixture / "no_todo_instructions.py"

    config = LinterConfig(
        custom_rules=[str(rule_file)],
        rules={"no-todo-instructions": {"enabled": True}},
    )
    context = RepositoryContext(fixture)
    linter = Linter(context, config)
    violations = linter.run()

    todo_violations = [v for v in violations if v.rule_id == "no-todo-instructions"]
    assert (
        len(todo_violations) == 2
    ), f"Expected 2 violations, got {len(todo_violations)}: {todo_violations}"
    messages = [v.message for v in todo_violations]
    assert any("TODO" in m for m in messages)
    assert any("FIXME" in m for m in messages)
    assert all(v.line is not None for v in todo_violations)


def test_custom_rule_tree_example_autofix(tmp_path):
    """Test the docs custom rule example: autofix removes TODO/FIXME lines."""
    fixture = copy_fixture("custom-rule-tree-example", tmp_path)
    rule_file = fixture / "no_todo_instructions.py"

    config = LinterConfig(
        custom_rules=[str(rule_file)],
        rules={"no-todo-instructions": {"enabled": True}},
    )
    context = RepositoryContext(fixture)
    linter = Linter(context, config)
    violations = linter.run()
    todo_violations = [v for v in violations if v.rule_id == "no-todo-instructions"]

    rule = next(r for r in linter.rules if r.rule_id == "no-todo-instructions")
    fixes = rule.fix(context, todo_violations)
    assert len(fixes) == 1
    assert "TODO" not in fixes[0].fixed_content
    assert "FIXME" not in fixes[0].fixed_content

    claude_md = fixture / "CLAUDE.md"
    original_line_count = len(claude_md.read_text().splitlines())
    claude_md.write_text(fixes[0].fixed_content, encoding="utf-8")
    invalidate_read_caches(claude_md)

    assert len(claude_md.read_text().splitlines()) == original_line_count - 2

    context2 = RepositoryContext(fixture)
    linter2 = Linter(context2, config)
    violations2 = linter2.run()
    remaining = [v for v in violations2 if v.rule_id == "no-todo-instructions"]
    assert remaining == [], f"Expected 0 violations after fix, got {remaining}"

    fixes2 = rule.fix(context2, remaining)
    assert fixes2 == []


def test_custom_rule_resolved_via_find_config(tmp_path):
    """Integration: find_config walks up, from_file sets config_dir, linter resolves the rule."""
    repo_root = copy_fixture("custom-rule-config", tmp_path)
    plugin_dir = repo_root / "plugins" / "my-plugin"

    config_path = find_config(plugin_dir)
    assert config_path is not None
    assert config_path.parent == repo_root

    config = LinterConfig.from_file(config_path)
    assert config.config_dir == repo_root

    context = RepositoryContext(plugin_dir)
    linter = Linter(context, config)

    rule_ids = [r.rule_id for r in linter.rules]
    assert "repo-root-rule" in rule_ids

    violations = linter.run()
    assert any(v.rule_id == "repo-root-rule" for v in violations)


def test_no_custom_rules_skips_custom_rules(valid_plugin, temp_dir):
    """--no-custom-rules should prevent custom rules from loading."""
    custom_rule_file = temp_dir / "custom_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class AlwaysFailRule(Rule):
    @property
    def rule_id(self) -> str:
        return "always-fail"

    @property
    def description(self) -> str:
        return "Always fails"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("this should not run")]
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    linter = Linter(context, config, no_custom_rules=True)
    rule_ids = [r.rule_id for r in linter.rules]
    assert "always-fail" not in rule_ids

    violations = linter.run()
    assert not any(v.rule_id == "always-fail" for v in violations)
