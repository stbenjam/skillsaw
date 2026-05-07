"""
Tests for main linter functionality
"""

import sys
from pathlib import Path


from skillsaw.linter import Linter
from skillsaw.context import RepositoryContext
from skillsaw.config import LinterConfig


def test_linter_passes_valid_plugin(valid_plugin):
    """Test that linter passes valid plugin"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    linter = Linter(context, config)

    violations = linter.run()
    errors, warnings, info = linter.get_counts(violations)

    assert errors == 0
    assert warnings == 0


def test_linter_passes_marketplace(marketplace_repo):
    """Test that linter passes valid marketplace"""
    context = RepositoryContext(marketplace_repo)
    config = LinterConfig.default()
    linter = Linter(context, config)

    violations = linter.run()
    errors, warnings, info = linter.get_counts(violations)

    # Should have no errors (warnings are ok - e.g. missing README)
    assert errors == 0


def test_linter_detects_errors(temp_dir):
    """Test that linter detects errors in invalid plugin"""
    # Create a minimal plugin structure with missing plugin.json
    plugin_dir = temp_dir / "bad-plugin"
    plugin_dir.mkdir()

    # Create .claude-plugin dir but no plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    context = RepositoryContext(plugin_dir)
    config = LinterConfig.default()

    # Enable plugin-json-required
    config.rules["plugin-json-required"] = {"enabled": True, "severity": "error"}

    linter = Linter(context, config)
    violations = linter.run()
    errors, warnings, info = linter.get_counts(violations)

    # Should detect missing plugin.json as error
    assert errors > 0


def test_linter_respects_disabled_rules(valid_plugin):
    """Test that disabled rules are not checked"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    # Disable all rules
    for rule_id in config.rules:
        config.rules[rule_id]["enabled"] = False

    linter = Linter(context, config)

    # Should have no rules loaded
    assert len(linter.rules) == 0


def test_linter_passes_rule_config(valid_plugin):
    """Test that per-rule config from .skillsaw.yaml reaches rule instances"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    # Override recommended-fields for plugin-json-valid
    config.rules["plugin-json-valid"]["recommended-fields"] = ["description"]

    linter = Linter(context, config)

    # Find the plugin-json-valid rule and verify it got the config
    pjv_rules = [r for r in linter.rules if r.rule_id == "plugin-json-valid"]
    assert len(pjv_rules) == 1
    assert pjv_rules[0].config.get("recommended-fields") == ["description"]


def test_linter_warns_on_unknown_rule_id(valid_plugin):
    """Test that unknown rule IDs in config produce warnings"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["nonexistent-rule"] = {"enabled": True, "severity": "error"}

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [
        v for v in violations if v.rule_id == "invalid-config" and "nonexistent-rule" in v.message
    ]
    assert len(unknown_warnings) == 1
    assert unknown_warnings[0].severity.value == "warning"


def test_linter_warns_on_multiple_unknown_rule_ids(valid_plugin):
    """Test that each unknown rule ID produces its own warning"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()
    config.rules["fake-rule-one"] = {"enabled": True}
    config.rules["fake-rule-two"] = {"enabled": False}

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [v for v in violations if v.rule_id == "invalid-config"]
    assert len(unknown_warnings) == 2


def test_linter_no_warning_for_known_rule_ids(valid_plugin):
    """Test that valid rule IDs do not trigger unknown-rule warnings"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    linter = Linter(context, config)
    violations = linter.run()

    unknown_warnings = [v for v in violations if v.rule_id == "invalid-config"]
    assert len(unknown_warnings) == 0


def test_self_lint():
    """Skillsaw's own .claude/ directory should pass linting with no errors"""
    repo_root = Path(__file__).parent.parent
    context = RepositoryContext(repo_root)
    config = LinterConfig.default()
    linter = Linter(context, config)

    violations = linter.run()
    errors = [v for v in violations if v.severity.value == "error"]

    assert len(errors) == 0, f"Self-lint found errors: {errors}"
