"""
Tests for promptfoo eval validation rules.
"""

import textwrap
from pathlib import Path

import yaml

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.promptfoo import (
    PromptfooAssertionsRule,
    PromptfooMetadataRule,
    PromptfooValidRule,
)


def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _write_raw_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _make_plugin(tmp: Path, name: str = "test-plugin") -> Path:
    """Create a minimal plugin directory."""
    plugin = tmp / name
    claude_dir = plugin / ".claude-plugin"
    claude_dir.mkdir(parents=True)
    (claude_dir / "plugin.json").write_text(f'{{"name": "{name}"}}')
    return plugin


def _make_skill(tmp: Path, name: str = "test-skill") -> Path:
    """Create a minimal skill directory."""
    skill = tmp / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A skill\n---\n")
    return skill


# ---------------------------------------------------------------------------
# Default config state
# ---------------------------------------------------------------------------


def test_promptfoo_valid_auto_enabled():
    config = LinterConfig.default()
    assert config.rules["promptfoo-valid"]["enabled"] == "auto"


def test_promptfoo_assertions_disabled_by_default():
    config = LinterConfig.default()
    assert config.rules["promptfoo-assertions"]["enabled"] is False


def test_promptfoo_metadata_disabled_by_default():
    config = LinterConfig.default()
    assert config.rules["promptfoo-metadata"]["enabled"] is False


# ---------------------------------------------------------------------------
# promptfoo-valid
# ---------------------------------------------------------------------------


def test_valid_config_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "smoke.yaml",
        {
            "description": "Smoke test",
            "providers": [{"id": "test"}],
            "prompts": ["{{prompt}}"],
            "tests": [
                {
                    "description": "basic",
                    "vars": {"prompt": "hello"},
                    "assert": [{"type": "contains", "value": "world"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_valid_skill_evals_passes(temp_dir):
    skill = _make_skill(temp_dir)
    _write_yaml(
        skill / "evals" / "test.yaml",
        {
            "tests": [{"description": "t1", "vars": {"prompt": "hi"}}],
        },
    )
    context = RepositoryContext(skill)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_invalid_yaml_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    evals_dir = plugin / "evals"
    evals_dir.mkdir()
    (evals_dir / "bad.yaml").write_text("{not: valid: yaml: [")
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "Invalid YAML" in violations[0].message


def test_not_a_mapping_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_raw_yaml(plugin / "evals" / "list.yaml", "- item1\n- item2\n")
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "mapping" in violations[0].message.lower()


def test_missing_tests_key_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-tests.yaml",
        {"description": "Missing tests", "providers": [{"id": "test"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "'tests'" in violations[0].message


def test_tests_not_array_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-tests.yaml",
        {"tests": "not-an-array"},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "array" in violations[0].message


def test_test_not_mapping_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-entry.yaml",
        {"tests": ["just-a-string"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "mapping" in violations[0].message.lower()


def test_missing_description_warns(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-desc.yaml",
        {"tests": [{"vars": {"prompt": "hello"}}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "description" in violations[0].message
    assert violations[0].severity == Severity.WARNING


def test_assert_not_array_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-assert.yaml",
        {"tests": [{"description": "t", "assert": "not-an-array"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "'assert' must be an array" in violations[0].message


def test_assert_entry_missing_type_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-type.yaml",
        {"tests": [{"description": "t", "assert": [{"value": "foo"}]}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "'type'" in violations[0].message


def test_assert_entry_non_dict_rejected(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "non-dict-assert.yaml",
        {"tests": [{"description": "t", "assert": ["just-a-string", 42]}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 2
    assert all("must be a mapping" in v.message for v in violations)


def test_no_evals_dir_skips(temp_dir):
    plugin = _make_plugin(temp_dir)
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_yml_extension_discovered(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "test.yml",
        {"tests": [{"description": "yml test", "vars": {"prompt": "hi"}}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_multiple_files_validated(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "good.yaml",
        {"tests": [{"description": "ok"}]},
    )
    _write_yaml(
        plugin / "evals" / "bad.yaml",
        {"tests": "not-a-list"},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# promptfoo-assertions
# ---------------------------------------------------------------------------


def test_assertions_default_severity():
    rule = PromptfooAssertionsRule()
    assert rule.default_severity() == Severity.WARNING


def test_assertions_all_required_in_default_test_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "ok.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": 0.50},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [{"description": "basic", "vars": {"prompt": "hi"}}],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 0


def test_assertions_split_between_default_and_test_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "split.yaml",
        {
            "defaultTest": {"assert": [{"type": "latency", "threshold": 30000}]},
            "tests": [
                {
                    "description": "has cost",
                    "assert": [{"type": "cost", "threshold": 0.50}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 0


def test_assertions_missing_type_reported(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "missing.yaml",
        {
            "tests": [
                {
                    "description": "no guards",
                    "assert": [{"type": "contains", "value": "hello"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 1
    assert "cost" in violations[0].message
    assert "latency" in violations[0].message


def test_assertions_partially_missing_reported(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "partial.yaml",
        {
            "tests": [
                {
                    "description": "has-one-guard",
                    "assert": [{"type": "cost", "threshold": 1.0}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 1
    assert "latency" in violations[0].message
    assert "cost" not in violations[0].message


def test_assertions_custom_required_types(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "custom.yaml",
        {
            "tests": [
                {
                    "description": "needs skill-used",
                    "assert": [{"type": "contains", "value": "x"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"required-types": ["skill-used"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "skill-used" in violations[0].message


def test_assertions_max_cost_threshold_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "budget-ok.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": 0.50},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [{"description": "ok"}],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"max-cost-threshold": 1.0})
    violations = rule.check(context)
    assert len(violations) == 0


def test_assertions_max_cost_threshold_exceeded_default_test(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "over-budget.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": 5.0},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [{"description": "expensive"}],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"max-cost-threshold": 2.0})
    violations = rule.check(context)
    assert any("5.0" in v.message and "2.0" in v.message for v in violations)


def test_assertions_max_cost_threshold_exceeded_per_test(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "per-test-budget.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": 0.50},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [
                {
                    "description": "override",
                    "assert": [{"type": "cost", "threshold": 10.0}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"max-cost-threshold": 2.0})
    violations = rule.check(context)
    cost_violations = [v for v in violations if "10.0" in v.message]
    assert len(cost_violations) == 1


def test_assertions_non_numeric_threshold_skipped(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "non-numeric.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": "not-a-number"},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [{"description": "ok"}],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"max-cost-threshold": 2.0})
    violations = rule.check(context)
    assert not any("cost threshold" in v.message for v in violations)


def test_assertions_no_tests_skips(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(plugin / "evals" / "empty.yaml", {"description": "empty"})
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 0


def test_assertions_uses_configured_severity(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "budget.yaml",
        {
            "defaultTest": {
                "assert": [
                    {"type": "cost", "threshold": 5.0},
                    {"type": "latency", "threshold": 30000},
                ]
            },
            "tests": [{"description": "expensive"}],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"max-cost-threshold": 2.0, "severity": "error"})
    violations = rule.check(context)
    cost_violations = [v for v in violations if "cost threshold" in v.message]
    assert len(cost_violations) >= 1
    assert all(v.severity == Severity.ERROR for v in cost_violations)


# ---------------------------------------------------------------------------
# promptfoo-metadata
# ---------------------------------------------------------------------------


def test_metadata_default_severity():
    rule = PromptfooMetadataRule()
    assert rule.default_severity() == Severity.WARNING


def test_metadata_all_keys_present_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "ok.yaml",
        {
            "tests": [
                {
                    "description": "good meta",
                    "metadata": {"token-usage": "small", "tier": "fast"},
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 0


def test_metadata_missing_reports_all_keys(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-meta.yaml",
        {"tests": [{"description": "no metadata"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 1
    assert "metadata" in violations[0].message
    assert "tier" in violations[0].message
    assert "token-usage" in violations[0].message


def test_metadata_partial_missing(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "partial.yaml",
        {
            "tests": [
                {
                    "description": "only usage",
                    "metadata": {"token-usage": "medium"},
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 1
    assert "tier" in violations[0].message
    assert "token-usage" not in violations[0].message


def test_metadata_not_mapping_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-meta.yaml",
        {"tests": [{"description": "bad", "metadata": "not-a-dict"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 1
    assert "mapping" in violations[0].message.lower()


def test_metadata_custom_required_keys(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "custom.yaml",
        {
            "tests": [
                {
                    "description": "needs author",
                    "metadata": {"token-usage": "small"},
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooMetadataRule(config={"required-keys": ["author", "org"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "author" in violations[0].message
    assert "org" in violations[0].message


def test_metadata_extra_keys_accepted(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "extra.yaml",
        {
            "tests": [
                {
                    "description": "extra ok",
                    "metadata": {
                        "token-usage": "large",
                        "tier": "heavy",
                        "judge-size": "opus",
                        "custom-field": "value",
                    },
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 0


def test_metadata_multiple_tests_independent(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "multi.yaml",
        {
            "tests": [
                {
                    "description": "good",
                    "metadata": {"token-usage": "small", "tier": "fast"},
                },
                {"description": "bad", "metadata": {"token-usage": "medium"}},
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 1
    assert "bad" in violations[0].message


# ---------------------------------------------------------------------------
# Integration: rule coverage guard
# ---------------------------------------------------------------------------


def test_all_promptfoo_rules_in_builtin_list():
    from skillsaw.rules.builtin import BUILTIN_RULES

    rule_classes = {PromptfooValidRule, PromptfooAssertionsRule, PromptfooMetadataRule}
    registered = {r for r in BUILTIN_RULES if r in rule_classes}
    assert registered == rule_classes


def test_all_promptfoo_rules_in_default_config():
    config = LinterConfig.default()
    for rule_id in ("promptfoo-valid", "promptfoo-assertions", "promptfoo-metadata"):
        assert rule_id in config.rules, f"{rule_id} not in default config"
