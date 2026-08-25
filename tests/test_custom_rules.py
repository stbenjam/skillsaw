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

    # Raises ValueError so the CLI surfaces a friendly error, not a traceback.
    with pytest.raises(ValueError, match="Custom rule file not found"):
        Linter(context, config)


def test_load_custom_rule_unresolvable_path(valid_plugin, monkeypatch):
    """An unsafe custom-rule path must fail cleanly before filesystem access."""
    config = LinterConfig(custom_rules=["unresolvable_rule.py"])
    context = RepositoryContext(valid_plugin)
    monkeypatch.setattr("skillsaw.linter.safe_resolve", lambda path: None)

    with pytest.raises(ValueError, match="Custom rule path could not be resolved"):
        Linter(context, config)


def test_load_custom_rule_stat_error_preserves_cause(valid_plugin, monkeypatch):
    """Stat/access failures must stay distinct from an absent custom rule."""
    config = LinterConfig(custom_rules=["unreadable_rule.py"])
    context = RepositoryContext(valid_plugin)
    real_stat = Path.stat

    def unreadable_stat(path, *args, **kwargs):
        """Raise an access failure for the targeted custom-rule path."""
        if path.name == "unreadable_rule.py":
            raise PermissionError("permission denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unreadable_stat)

    with pytest.raises(
        ValueError,
        match=r"Custom rule path cannot be accessed: .*unreadable_rule\.py: permission denied",
    ):
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

    # Wrapped as ValueError (CLI-friendly); message names the offending file.
    with pytest.raises(ValueError, match="Failed to load custom rule"):
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

    # Wrapped as ValueError so the CLI shows a friendly error, not a traceback.
    with pytest.raises(ValueError, match="Failed to load custom rule"):
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

    # Wrapped as ValueError; the original ImportError detail is preserved.
    with pytest.raises(ValueError, match="cannot import name 'NonExistentClass'"):
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


def test_no_custom_rules_does_not_flag_configured_custom_rule_ids(valid_plugin, temp_dir):
    """Config entries for custom rules must not warn as 'unknown rule' when
    --no-custom-rules prevents loading them (e.g. strict CI gates)."""
    custom_rule_file = temp_dir / "custom_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class MyCustomRule(Rule):
    @property
    def rule_id(self) -> str:
        return "my-custom-rule"

    @property
    def description(self) -> str:
        return "Custom"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")

    config = LinterConfig(
        custom_rules=[str(custom_rule_file)],
        rules={"my-custom-rule": {"enabled": True, "severity": "error"}},
    )
    context = RepositoryContext(valid_plugin)

    violations = Linter(context, config, no_custom_rules=True).run()
    assert not any(v.rule_id == "invalid-config" for v in violations)

    # Without custom-rules files configured, a typo'd ID still warns.
    typo_config = LinterConfig(rules={"my-custom-rule": {"enabled": True}})
    context = RepositoryContext(valid_plugin)
    violations = Linter(context, typo_config, no_custom_rules=True).run()
    assert any(v.rule_id == "invalid-config" for v in violations)


def _write_custom_rule(path, rule_id, since=None):
    since_attr = f'\n    since = "{since}"' if since else ""
    path.write_text(f"""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List


class MyRule(Rule):{since_attr}
    @property
    def rule_id(self) -> str:
        return "{rule_id}"

    @property
    def description(self) -> str:
        return "custom"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")


def test_custom_rule_is_version_gated(valid_plugin, temp_dir):
    """A custom rule's `since` must be honored, like builtin rules (§1.10)."""
    rule_file = temp_dir / "future_rule.py"
    _write_custom_rule(rule_file, "future-custom-rule", since="99.0.0")
    config = LinterConfig(version="0.1.0", custom_rules=[str(rule_file)])
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, config)
    rule_ids = {r.rule_id for r in linter.rules}
    assert "future-custom-rule" not in rule_ids


def test_two_custom_rule_files_distinct_modules(valid_plugin, temp_dir):
    """Two custom rule files must not clobber each other in sys.modules (§1.10)."""
    a = temp_dir / "rule-a.py"
    b = temp_dir / "rule_b.py"
    _write_custom_rule(a, "custom-rule-a")
    _write_custom_rule(b, "custom-rule-b")
    config = LinterConfig(version="0.1.0", custom_rules=[str(a), str(b)])
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, config)
    rules = {r.rule_id: r for r in linter.rules}
    rule_ids = set(rules)
    assert "custom-rule-a" in rule_ids
    assert "custom-rule-b" in rule_ids

    # Prove module isolation: each file is registered under a distinct
    # sys.modules key (they previously all loaded as "custom_rule").
    import sys

    mod_a = type(rules["custom-rule-a"]).__module__
    mod_b = type(rules["custom-rule-b"]).__module__
    assert mod_a != mod_b
    assert mod_a.startswith("skillsaw_custom_rule_a_")
    assert mod_b.startswith("skillsaw_custom_rule_b_")
    assert mod_a in sys.modules
    assert mod_b in sys.modules
    assert sys.modules[mod_a] is not sys.modules[mod_b]


def test_custom_rule_constructor_error_is_wrapped(valid_plugin, temp_dir):
    """Errors after importing a custom rule file should still be CLI-friendly."""
    custom_rule_file = temp_dir / "broken_constructor_rule.py"
    custom_rule_file.write_text("""
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List


class BrokenRule(Rule):
    def __init__(self, config=None):
        raise RuntimeError("constructor boom")

    @property
    def rule_id(self) -> str:
        return "broken-custom-rule"

    @property
    def description(self) -> str:
        return "broken"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
""")
    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    with pytest.raises(ValueError, match="Failed to load custom rule.*constructor boom"):
        Linter(context, config)


def test_abstract_helper_rule_does_not_abort_file(valid_plugin, temp_dir):
    """An abstract helper Rule subclass in a custom-rules file must be skipped,
    not instantiated — otherwise the whole file is dropped (issue #322).

    The builtin and plugin loaders already skip ``inspect.isabstract`` classes;
    the custom-rule path must match, so a concrete rule sharing the file still
    loads and runs.
    """
    custom_rule_file = temp_dir / "abstract_helper_rule.py"
    custom_rule_file.write_text("""
from abc import abstractmethod
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List


class BaseHelperRule(Rule):
    # Abstract helper: subclasses share this scaffolding. Instantiating it
    # would raise TypeError, which previously aborted the entire file.
    @abstractmethod
    def targets(self) -> List[str]:
        ...

    @property
    def description(self) -> str:
        return "shared helper description"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("helper violation")]


class ConcreteHelperRule(BaseHelperRule):
    @property
    def rule_id(self) -> str:
        return "concrete-helper-rule"

    def targets(self) -> List[str]:
        return ["*.md"]
""")

    config = LinterConfig(custom_rules=[str(custom_rule_file)])
    context = RepositoryContext(valid_plugin)

    linter = Linter(context, config)

    rule_ids = [rule.rule_id for rule in linter.rules]
    assert "concrete-helper-rule" in rule_ids

    violations = linter.run()
    assert any(v.rule_id == "concrete-helper-rule" for v in violations)


def test_unknown_skip_rule_raises(valid_plugin):
    """A typo in --skip-rule must error, not silently leave the rule running."""
    context = RepositoryContext(valid_plugin)
    with pytest.raises(ValueError, match="Unknown rule.*skip-rule"):
        Linter(context, LinterConfig.default(), skip_rule_ids={"no-such-rule-xyz"})


def test_valid_skip_rule_accepted(valid_plugin):
    context = RepositoryContext(valid_plugin)
    linter = Linter(context, LinterConfig.default(), skip_rule_ids={"content-weak-language"})
    assert "content-weak-language" not in {r.rule_id for r in linter.rules}


CUSTOM_RULE_WITH_SCHEMA = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class SchemaCustomRule(Rule):
    config_schema = {
        "opt": {"type": "path", "default": "x", "description": "An option."},
    }

    @property
    def rule_id(self) -> str:
        return "schema-custom-rule"

    @property
    def description(self) -> str:
        return "A custom rule that declares a config_schema"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""

CUSTOM_RULE_WITHOUT_SCHEMA = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class BareCustomRule(Rule):
    @property
    def rule_id(self) -> str:
        return "bare-custom-rule"

    @property
    def description(self) -> str:
        return "A custom rule with no config_schema"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def _custom_option_warnings(violations, rule_id):
    return [
        v
        for v in violations
        if v.rule_id == "invalid-config"
        and "option" in v.message.lower()
        and f"'{rule_id}'" in v.message
    ]


def test_custom_rule_without_schema_skips_option_validation(valid_plugin, temp_dir):
    """Third-party rules that declare no schema never get option warnings."""
    rule_file = temp_dir / "bare_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITHOUT_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["bare-custom-rule"] = {"enabled": True, "whatever-key": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "bare-custom-rule") == []


def test_schema_less_custom_rule_still_validates_universal_exclude(valid_plugin, temp_dir):
    """The universal `exclude` key is the linter's contract, not the rule's:
    its shape check runs even without a schema, because a malformed value
    fails open in _is_rule_excluded and would otherwise be silently inert."""
    rule_file = temp_dir / "bare_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITHOUT_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["bare-custom-rule"] = {"enabled": True, "exclude": "*.md"}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "bare-custom-rule")
    assert len(warnings) == 1
    assert "expects list of strings" in warnings[0].message


CUSTOM_RULE_WITH_RAISING_STRICT_OPTIONS = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class _Raising:
    def __bool__(self):
        raise RuntimeError("no truth for you")

class TrickyRule(Rule):
    config_schema = {"opt": {"type": "int", "default": 1}}
    strict_options = _Raising()

    @property
    def rule_id(self) -> str:
        return "tricky-strict-rule"

    @property
    def description(self) -> str:
        return "strict_options refuses truth testing"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_raising_strict_options_does_not_abort_validation(valid_plugin, temp_dir):
    """bool(strict_options) happens inside the guard: a third-party object
    whose __bool__ raises downgrades the rule to schema-less instead of
    aborting the lint."""
    rule_file = temp_dir / "tricky_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_RAISING_STRICT_OPTIONS)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["tricky-strict-rule"] = {"enabled": True, "mystery-opt": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "tricky-strict-rule") == []


CUSTOM_RULE_WITH_RAISING_ENTRY_GET = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class _RaisingGet(dict):
    def get(self, *args, **kwargs):
        raise RuntimeError("no get for you")

class EntryRule(Rule):
    config_schema = {"opt": _RaisingGet({"type": "int", "default": 1})}

    @property
    def rule_id(self) -> str:
        return "raising-entry-rule"

    @property
    def description(self) -> str:
        return "schema entry is a dict subclass with a raising get()"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_raising_schema_entry_get_still_validates(valid_plugin, temp_dir):
    """Schema entries are detached (dict-copied) inside the guard, so a dict
    subclass whose get() raises neither aborts the lint nor skips the type
    check its plain contents describe."""
    rule_file = temp_dir / "entry_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_RAISING_ENTRY_GET)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["raising-entry-rule"] = {"enabled": True, "opt": "not-an-int"}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "raising-entry-rule")
    assert len(warnings) == 1
    assert "expects int, got str" in warnings[0].message


CUSTOM_RULE_SHADOWING_BUILTIN = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class ShadowRule(Rule):
    config_schema = {"custom-opt": {"type": "int", "default": 1}}

    @property
    def rule_id(self) -> str:
        return "agentskill-description"

    @property
    def description(self) -> str:
        return "Shadows a builtin rule ID"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_builtin_id_collision_keeps_builtin_validation_identity(valid_plugin, temp_dir):
    """A custom rule reusing a builtin ID loses the validation-ownership
    race to the builtin class; the unknown-option hint must agree and point
    at the builtin's explain page rather than going silent as if custom."""
    rule_file = temp_dir / "shadow_rule.py"
    rule_file.write_text(CUSTOM_RULE_SHADOWING_BUILTIN)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["agentskill-description"] = {"zzz-unrelated-key": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "agentskill-description")
    assert len(warnings) == 1
    assert "skillsaw explain agentskill-description" in warnings[0].message


def test_custom_rule_with_schema_opts_into_option_validation(valid_plugin, temp_dir):
    """Declaring a config_schema opts a custom rule into unknown-key warnings;
    an unmapped type like 'path' must not crash or type-warn."""
    rule_file = temp_dir / "schema_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["schema-custom-rule"] = {"enabled": True, "oops": 1, "opt": 123}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "schema-custom-rule")
    assert len(warnings) == 1
    assert "Unknown option 'oops'" in warnings[0].message


def test_disabled_custom_rule_still_validates_options(valid_plugin, temp_dir):
    """Recorded rule classes make validation independent of enablement."""
    rule_file = temp_dir / "schema_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["schema-custom-rule"] = {"enabled": False, "oops": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "schema-custom-rule")
    assert len(warnings) == 1
    assert "Unknown option 'oops'" in warnings[0].message
    assert "skillsaw explain" not in warnings[0].message


CUSTOM_RULE_WITH_NONSTRICT_SCHEMA = CUSTOM_RULE_WITH_SCHEMA.replace(
    "class SchemaCustomRule(Rule):",
    "class SchemaCustomRule(Rule):\n    strict_options = False",
)


def test_custom_rule_can_allow_additional_options_during_migration(valid_plugin, temp_dir):
    rule_file = temp_dir / "nonstrict_schema_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_NONSTRICT_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["schema-custom-rule"] = {"enabled": True, "legacy-opt": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "schema-custom-rule") == []


CUSTOM_RULE_WITH_LIST_TYPE_SCHEMA = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class ListTypeSchemaRule(Rule):
    config_schema = {
        "opt": {"type": ["string"], "default": "x", "description": "JSON-Schema-style type."},
    }

    @property
    def rule_id(self) -> str:
        return "list-type-schema-rule"

    @property
    def description(self) -> str:
        return "A custom rule with a non-string schema type"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_unhashable_schema_type_does_not_crash(valid_plugin, temp_dir):
    """A JSON-Schema-style list `type` must not crash the type check."""
    rule_file = temp_dir / "list_type_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_LIST_TYPE_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["list-type-schema-rule"] = {"enabled": True, "opt": 123}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "list-type-schema-rule") == []


CUSTOM_RULE_WITH_MALFORMED_SCHEMA = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class MalformedSchemaRule(Rule):
    config_schema = ["markers", "levels"]

    @property
    def rule_id(self) -> str:
        return "malformed-schema-rule"

    @property
    def description(self) -> str:
        return "A custom rule whose config_schema is not a dict"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_malformed_non_dict_schema_does_not_crash(valid_plugin, temp_dir):
    """A truthy non-dict config_schema is treated as undeclared, not a crash."""
    rule_file = temp_dir / "malformed_schema_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_MALFORMED_SCHEMA)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["malformed-schema-rule"] = {"enabled": True, "markers": ["x"]}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "malformed-schema-rule") == []


CUSTOM_RULE_WITH_STR_SCHEMA = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class StrOptionRule(Rule):
    config_schema = {
        "budget-file": {"type": "str", "default": "evals/budget.yaml", "description": "Path."},
    }

    @property
    def rule_id(self) -> str:
        return "str-option-rule"

    @property
    def description(self) -> str:
        return "A custom rule with a str-typed option"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_str_typed_option_is_validated(valid_plugin, temp_dir):
    """'str'/'string' schema types are type-checked like the builtin types."""
    rule_file = temp_dir / "str_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_STR_SCHEMA)

    for value, expected in (
        (123, "expects str, got int"),
        (True, "expects str, got bool"),
        (None, "expects str, got null"),
    ):
        config = LinterConfig(custom_rules=[str(rule_file)])
        config.rules["str-option-rule"] = {"enabled": True, "budget-file": value}
        violations = Linter(RepositoryContext(valid_plugin), config).run()
        warnings = _custom_option_warnings(violations, "str-option-rule")
        assert len(warnings) == 1, value
        assert expected in warnings[0].message

    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["str-option-rule"] = {"enabled": True, "budget-file": "budgets/q3.yaml"}
    violations = Linter(RepositoryContext(valid_plugin), config).run()
    assert _custom_option_warnings(violations, "str-option-rule") == []


def test_json_schema_type_aliases_are_validated(valid_plugin, temp_dir):
    schema = """
from skillsaw import Rule, Severity

class AliasTypeRule(Rule):
    config_schema = {
        "integer-opt": {"type": "integer", "default": 1, "description": "Integer."},
        "number-opt": {"type": "number", "default": 1.0, "description": "Number."},
        "boolean-opt": {"type": "boolean", "default": True, "description": "Boolean."},
        "array-opt": {"type": "array", "default": [], "description": "Array."},
        "object-opt": {"type": "object", "default": {}, "description": "Object."},
        "string-opt": {"type": "string", "default": "x", "description": "String."},
    }
    rule_id = "alias-type-rule"
    description = "Alias types"
    def default_severity(self): return Severity.WARNING
    def check(self, context): return []
"""
    rule_file = temp_dir / "alias_type_rule.py"
    rule_file.write_text(schema)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["alias-type-rule"] = {
        "enabled": True,
        "integer-opt": True,
        "number-opt": False,
        "boolean-opt": 1,
        "array-opt": {},
        "object-opt": [],
        "string-opt": 1,
    }

    warnings = _custom_option_warnings(
        Linter(RepositoryContext(valid_plugin), config).run(), "alias-type-rule"
    )
    assert len(warnings) == 6


CUSTOM_RULE_WITH_NONSTRING_SCHEMA_KEY = """
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List

class NonStringKeySchemaRule(Rule):
    config_schema = {
        1: {"type": "int", "default": 0, "description": "Bogus key."},
        "opt": {"type": "int", "default": 0, "description": "Real option."},
    }

    @property
    def rule_id(self) -> str:
        return "nonstring-key-schema-rule"

    @property
    def description(self) -> str:
        return "A custom rule whose schema has a non-string key"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
"""


def test_nonstring_schema_key_does_not_crash_suggestions(valid_plugin, temp_dir):
    """A non-string schema key must not crash sorted() in did-you-mean, and
    unknown config keys must still warn."""
    rule_file = temp_dir / "nonstring_key_rule.py"
    rule_file.write_text(CUSTOM_RULE_WITH_NONSTRING_SCHEMA_KEY)
    config = LinterConfig(custom_rules=[str(rule_file)])
    config.rules["nonstring-key-schema-rule"] = {"enabled": True, "oops": 1}

    violations = Linter(RepositoryContext(valid_plugin), config).run()
    warnings = _custom_option_warnings(violations, "nonstring-key-schema-rule")
    assert len(warnings) == 1
    assert "Unknown option 'oops'" in warnings[0].message
