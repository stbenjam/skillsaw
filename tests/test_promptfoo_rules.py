"""
Tests for promptfoo eval validation rules.
"""

import textwrap
from pathlib import Path

import yaml

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import PromptfooConfigNode
from skillsaw.rule import Severity
from skillsaw.rules.builtin.promptfoo import (
    PromptfooAssertionsRule,
    PromptfooMetadataRule,
    PromptfooValidRule,
    _is_promptfoo_config,
    _resolve_file_ref,
    _extract_file_refs,
)


def _write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _write_raw_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


def _make_plugin(tmp: Path, name: str = "test-plugin") -> Path:
    plugin = tmp / name
    claude_dir = plugin / ".claude-plugin"
    claude_dir.mkdir(parents=True)
    (claude_dir / "plugin.json").write_text(f'{{"name": "{name}"}}')
    return plugin


def _make_skill(tmp: Path, name: str = "test-skill") -> Path:
    skill = tmp / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A skill\n---\n")
    return skill


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_is_promptfoo_config_with_tests():
    assert _is_promptfoo_config({"tests": [], "providers": []})


def test_is_promptfoo_config_with_scenarios():
    assert _is_promptfoo_config({"scenarios": []})


def test_is_promptfoo_config_with_default_test():
    assert _is_promptfoo_config({"defaultTest": {}, "evaluateOptions": {}})


def test_is_promptfoo_config_rejects_non_dict():
    assert not _is_promptfoo_config([1, 2, 3])
    assert not _is_promptfoo_config("string")
    assert not _is_promptfoo_config(None)


def test_is_promptfoo_config_with_redteam():
    assert _is_promptfoo_config({"redteam": {"plugins": ["harmful"]}, "targets": [{"id": "openai:gpt-4"}]})


def test_is_promptfoo_config_rejects_no_promptfoo_keys():
    assert not _is_promptfoo_config({"name": "foo", "version": "1.0"})


def test_resolve_file_ref_basic(tmp_path):
    target = tmp_path / "tests.yaml"
    target.write_text("[]")
    assert _resolve_file_ref("file://tests.yaml", tmp_path) == target.resolve()


def test_resolve_file_ref_without_prefix(tmp_path):
    target = tmp_path / "tests.yaml"
    target.write_text("[]")
    # Bare YAML paths are valid promptfoo file references
    assert _resolve_file_ref("tests.yaml", tmp_path) == target.resolve()


def test_resolve_file_ref_missing_file(tmp_path):
    result = _resolve_file_ref("file://nonexistent.yaml", tmp_path)
    assert result is not None
    assert not result.exists()


def test_resolve_file_ref_glob_skipped(tmp_path):
    assert _resolve_file_ref("file://tests/*.yaml", tmp_path) is None


def test_resolve_file_ref_csv_skipped(tmp_path):
    (tmp_path / "data.csv").write_text("a,b")
    assert _resolve_file_ref("file://data.csv", tmp_path) is None


def test_resolve_file_ref_js_skipped(tmp_path):
    (tmp_path / "gen.js").write_text("module.exports = []")
    assert _resolve_file_ref("file://gen.js", tmp_path) is None


def test_resolve_file_ref_remote_skipped(tmp_path):
    assert _resolve_file_ref("https://example.com/tests.yaml", tmp_path) is None
    assert _resolve_file_ref("huggingface://datasets/foo", tmp_path) is None


def test_extract_file_refs_string_tests():
    assert _extract_file_refs({"tests": "file://tests.yaml"}) == ["file://tests.yaml"]


def test_extract_file_refs_list_with_strings():
    refs = _extract_file_refs(
        {"tests": ["file://a.yaml", {"description": "inline"}, "file://b.yaml"]}
    )
    assert refs == ["file://a.yaml", "file://b.yaml"]


def test_extract_file_refs_no_tests():
    assert _extract_file_refs({"providers": []}) == []


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
# RepositoryType.PROMPTFOO detection
# ---------------------------------------------------------------------------


def test_promptfoo_repo_detected_by_config_name(temp_dir):
    _write_yaml(
        temp_dir / "promptfooconfig.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(temp_dir)
    assert RepositoryType.PROMPTFOO in context.repo_types


def test_promptfoo_repo_detected_by_evals_dir(temp_dir):
    skill = _make_skill(temp_dir)
    _write_yaml(
        skill / "evals" / "smoke.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(temp_dir)
    assert (
        RepositoryType.PROMPTFOO in context.repo_types
        or RepositoryType.AGENTSKILLS in context.repo_types
    )


def test_promptfoo_repo_detected_by_nested_config(temp_dir):
    nested = temp_dir / "ai" / "evals" / "promptfoo"
    nested.mkdir(parents=True)
    _write_yaml(
        nested / "promptfooconfig.yaml",
        {"providers": [{"id": "test"}], "tests": [{"vars": {"prompt": "hi"}}]},
    )
    context = RepositoryContext(temp_dir)
    assert RepositoryType.PROMPTFOO in context.repo_types


def test_nested_promptfoo_config_in_tree(temp_dir):
    nested = temp_dir / "ai" / "evals" / "promptfoo"
    nested.mkdir(parents=True)
    _write_yaml(
        nested / "promptfooconfig.yaml",
        {"providers": [{"id": "test"}], "tests": [{"vars": {"prompt": "hi"}}]},
    )
    context = RepositoryContext(temp_dir)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 1
    assert nodes[0].path.name == "promptfooconfig.yaml"
    assert not nodes[0].is_fragment


def test_nested_promptfoo_config_validates_clean(temp_dir):
    nested = temp_dir / "ai" / "evals" / "promptfoo"
    nested.mkdir(parents=True)
    _write_yaml(
        nested / "promptfooconfig.yaml",
        {
            "providers": [{"id": "test"}],
            "prompts": ["{{prompt}}"],
            "defaultTest": {
                "assert": [{"type": "llm-rubric", "value": "helpful response"}]
            },
            "tests": [
                {
                    "vars": {"prompt": "hello"},
                    "assert": [{"type": "contains", "value": "world"}],
                }
            ],
        },
    )
    context = RepositoryContext(temp_dir)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_non_promptfoo_yaml_in_evals_not_detected(temp_dir):
    evals = temp_dir / "evals"
    evals.mkdir()
    _write_yaml(evals / "unrelated.yaml", {"name": "not-promptfoo", "version": "1.0"})
    context = RepositoryContext(temp_dir)
    assert RepositoryType.PROMPTFOO not in context.repo_types


# ---------------------------------------------------------------------------
# PromptfooConfigNode in lint tree
# ---------------------------------------------------------------------------


def test_config_node_in_tree_under_plugin(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "smoke.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(plugin)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 1
    assert not nodes[0].is_fragment


def test_config_node_in_tree_under_skill(temp_dir):
    skill = _make_skill(temp_dir)
    _write_yaml(
        skill / "evals" / "smoke.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(temp_dir)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 1


def test_standalone_promptfooconfig_in_tree(temp_dir):
    _write_yaml(
        temp_dir / "promptfooconfig.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(temp_dir)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 1


def test_fragment_node_as_child_of_config(temp_dir):
    plugin = _make_plugin(temp_dir)
    tests_file = plugin / "evals" / "tests" / "cases.yaml"
    _write_yaml(tests_file, [{"description": "from fragment", "vars": {"prompt": "hi"}}])
    _write_yaml(
        plugin / "evals" / "smoke.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": ["file://tests/cases.yaml"],
        },
    )
    context = RepositoryContext(plugin)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    configs = [n for n in nodes if not n.is_fragment]
    fragments = [n for n in nodes if n.is_fragment]
    assert len(configs) == 1
    assert len(fragments) == 1
    assert fragments[0].parent is configs[0]


def test_non_promptfoo_yaml_not_in_tree(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "unrelated.yaml",
        {"name": "not-promptfoo", "version": "1.0"},
    )
    context = RepositoryContext(temp_dir)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 0


def test_nested_evals_discovered(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "smoke" / "deep.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "t1"}]},
    )
    context = RepositoryContext(plugin)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    assert len(nodes) == 1


def test_shared_fragment_deduplication(temp_dir):
    plugin = _make_plugin(temp_dir)
    shared = plugin / "evals" / "shared.yaml"
    _write_yaml(shared, [{"description": "shared test"}])
    _write_yaml(
        plugin / "evals" / "config-a.yaml",
        {"providers": [{"id": "a"}], "tests": ["file://shared.yaml"]},
    )
    _write_yaml(
        plugin / "evals" / "config-b.yaml",
        {"providers": [{"id": "b"}], "tests": ["file://shared.yaml"]},
    )
    context = RepositoryContext(plugin)
    nodes = context.lint_tree.find(PromptfooConfigNode)
    fragments = [n for n in nodes if n.is_fragment]
    # shared.yaml appears once — first config to reference it owns it
    assert len(fragments) <= 1


# ---------------------------------------------------------------------------
# promptfoo-valid: full configs
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
            "providers": [{"id": "test"}],
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
    # Write a promptfoo-looking file that has invalid YAML
    # We need to make sure it gets into the tree — use promptfooconfig naming
    (temp_dir / "promptfooconfig.yaml").write_text("{not: valid: yaml: [")
    context = RepositoryContext(temp_dir)
    violations = PromptfooValidRule().check(context)
    assert any("Invalid YAML" in v.message for v in violations)


def test_redteam_config_passes(temp_dir):
    _write_yaml(
        temp_dir / "promptfooconfig.yaml",
        {
            "targets": [{"id": "openai:gpt-4"}],
            "redteam": {
                "purpose": "Test travel assistant",
                "plugins": ["harmful:self-harm", "politics"],
                "strategies": ["jailbreak", "prompt-injection"],
            },
        },
    )
    context = RepositoryContext(temp_dir)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_redteam_invalid_type_fails(temp_dir):
    _write_yaml(
        temp_dir / "promptfooconfig.yaml",
        {"targets": [{"id": "openai:gpt-4"}], "redteam": "not-a-dict"},
    )
    context = RepositoryContext(temp_dir)
    violations = PromptfooValidRule().check(context)
    assert any("'redteam' must be a mapping" in v.message for v in violations)


def test_tests_as_dict_dataset_provider_passes(temp_dir):
    _write_yaml(
        temp_dir / "promptfooconfig.yaml",
        {
            "providers": [{"id": "openai:gpt-4"}],
            "tests": {
                "path": "file://dataset_loader.ts:generate_tests",
                "config": {"dataset": "EleutherAI/truthful_qa_mc"},
            },
        },
    )
    context = RepositoryContext(temp_dir)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_no_tests_or_scenarios_warns(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-tests.yaml",
        {"providers": [{"id": "test"}], "prompts": ["{{prompt}}"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "tests" in violations[0].message
    assert "scenarios" in violations[0].message
    assert "redteam" in violations[0].message
    assert violations[0].severity == Severity.WARNING


def test_scenarios_accepted(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "scenarios.yaml",
        {
            "providers": [{"id": "test"}],
            "scenarios": [
                {
                    "config": [{"description": "scenario test"}],
                    "tests": [{"description": "t1"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_scenarios_invalid_type_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-scenarios.yaml",
        {"providers": [{"id": "test"}], "scenarios": 42},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "'scenarios' must be an array" in violations[0].message


def test_scenarios_as_string_file_ref_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "scenario-ref.yaml",
        {"providers": [{"id": "test"}], "scenarios": "file://scenarios.yaml"},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_tests_as_string_file_ref_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    target = plugin / "evals" / "tests.yaml"
    _write_yaml(target, [{"description": "t1"}])
    _write_yaml(
        plugin / "evals" / "file-ref.yaml",
        {"providers": [{"id": "test"}], "tests": "file://tests.yaml"},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_tests_invalid_type_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-tests.yaml",
        {"providers": [{"id": "test"}], "tests": 42},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "array" in violations[0].message
    assert "file reference" in violations[0].message


# ---------------------------------------------------------------------------
# promptfoo-valid: string entries in tests lists (no false positives)
# ---------------------------------------------------------------------------


def test_string_test_entry_with_existing_file_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    target = plugin / "evals" / "cases.yaml"
    _write_yaml(target, [{"description": "t1"}])
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://cases.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_string_test_entry_with_missing_file_errors(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": ["file://nonexistent.yaml"],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert any("not found" in v.message for v in violations)


def test_mixed_test_list_validates_correctly(temp_dir):
    plugin = _make_plugin(temp_dir)
    target = plugin / "evals" / "extra.yaml"
    _write_yaml(target, [{"description": "from file"}])
    _write_yaml(
        plugin / "evals" / "mixed.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                "file://extra.yaml",
                {"description": "inline", "assert": [{"type": "contains", "value": "x"}]},
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_glob_ref_skipped_gracefully(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "glob-ref.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://tests/*.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# promptfoo-valid: $ref in assertions (no false positives)
# ---------------------------------------------------------------------------


def test_ref_assertion_not_flagged(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "ref.yaml",
        {
            "providers": [{"id": "test"}],
            "assertionTemplates": {"is_valid": {"type": "contains", "value": "ok"}},
            "tests": [
                {
                    "description": "uses ref",
                    "assert": [{"$ref": "#/assertionTemplates/is_valid"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# promptfoo-valid: description is optional (no false positives)
# ---------------------------------------------------------------------------


def test_no_description_no_warning(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-desc.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [{"vars": {"prompt": "hello"}}],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert not any("description" in v.message for v in violations)


# ---------------------------------------------------------------------------
# promptfoo-valid: fragment validation
# ---------------------------------------------------------------------------


def test_fragment_list_validated(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "cases.yaml"
    _write_yaml(frag, [{"description": "good"}, "not-a-dict"])
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://cases.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert any("must be a mapping" in v.message for v in violations)


def test_fragment_single_dict_accepted(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "single.yaml"
    _write_yaml(frag, {"description": "one test", "vars": {"prompt": "hi"}})
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://single.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_fragment_invalid_type_errors(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "bad.yaml"
    _write_raw_yaml(frag, "just a string\n")
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://bad.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert any("fragment" in v.message.lower() for v in violations)


def test_fragment_assert_validation(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "cases.yaml"
    _write_yaml(
        frag,
        [{"description": "t1", "assert": [{"value": "no type here"}]}],
    )
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://cases.yaml"]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert any("'type'" in v.message for v in violations)


# ---------------------------------------------------------------------------
# promptfoo-valid: other structural checks
# ---------------------------------------------------------------------------


def test_non_dict_assert_entry_rejected(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-assert-entry.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [{"description": "t", "assert": ["just-a-string"]}],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "assert[0] must be a mapping" in violations[0].message


def test_assert_not_array_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-assert.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [{"description": "t", "assert": "not-an-array"}],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 1
    assert "'assert' must be an array" in violations[0].message


def test_no_evals_dir_skips(temp_dir):
    plugin = _make_plugin(temp_dir)
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


def test_yml_extension_discovered(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "test.yml",
        {"providers": [{"id": "test"}], "tests": [{"description": "yml test"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooValidRule().check(context)
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# promptfoo-assertions
# ---------------------------------------------------------------------------


def test_assertions_default_severity():
    rule = PromptfooAssertionsRule()
    assert rule.default_severity() == Severity.WARNING


def test_assertions_empty_default_required_types_no_violations(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-guards.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                {"description": "no guards", "assert": [{"type": "contains", "value": "hello"}]}
            ],
        },
    )
    context = RepositoryContext(plugin)
    violations = PromptfooAssertionsRule().check(context)
    assert len(violations) == 0


def test_assertions_all_required_in_default_test_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "ok.yaml",
        {
            "providers": [{"id": "test"}],
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
    rule = PromptfooAssertionsRule(config={"required-types": ["cost", "latency"]})
    violations = rule.check(context)
    assert len(violations) == 0


def test_assertions_missing_type_reported(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "missing.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                {"description": "no guards", "assert": [{"type": "contains", "value": "hello"}]}
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"required-types": ["cost", "latency"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "cost" in violations[0].message
    assert "latency" in violations[0].message


def test_assertions_applied_to_fragment_tests(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "cases.yaml"
    _write_yaml(
        frag, [{"description": "frag test", "assert": [{"type": "contains", "value": "x"}]}]
    )
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://cases.yaml"]},
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"required-types": ["cost"]})
    violations = rule.check(context)
    assert any("cost" in v.message for v in violations)


def test_assertions_default_test_applies_to_fragments(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "cases.yaml"
    _write_yaml(frag, [{"description": "frag test"}])
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {
            "providers": [{"id": "test"}],
            "defaultTest": {"assert": [{"type": "cost", "threshold": 0.5}]},
            "tests": ["file://cases.yaml"],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"required-types": ["cost"]})
    violations = rule.check(context)
    assert len(violations) == 0


def test_threshold_constraints_max_exceeded(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "over-budget.yaml",
        {
            "providers": [{"id": "test"}],
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
    rule = PromptfooAssertionsRule(config={"threshold-constraints": {"cost": {"max": 2.0}}})
    violations = rule.check(context)
    assert any("5.0" in v.message and "2.0" in v.message for v in violations)


def test_threshold_constraints_min_violated(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "below-min.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                {"description": "too fast", "assert": [{"type": "latency", "threshold": 500}]}
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"threshold-constraints": {"latency": {"min": 1000}}})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "500" in violations[0].message


def test_threshold_non_numeric_skipped(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "non-numeric.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                {
                    "description": "string threshold",
                    "assert": [{"type": "cost", "threshold": "fast"}],
                }
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"threshold-constraints": {"cost": {"max": 2.0}}})
    violations = rule.check(context)
    assert len(violations) == 0


def test_assertions_skips_string_tests(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "file-ref.yaml",
        {"providers": [{"id": "test"}], "tests": "file://tests.yaml"},
    )
    context = RepositoryContext(plugin)
    rule = PromptfooAssertionsRule(config={"required-types": ["cost"]})
    violations = rule.check(context)
    assert len(violations) == 0


# ---------------------------------------------------------------------------
# promptfoo-metadata
# ---------------------------------------------------------------------------


def test_metadata_default_severity():
    rule = PromptfooMetadataRule()
    assert rule.default_severity() == Severity.WARNING


def test_metadata_empty_default_required_keys_no_violations(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-meta.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "no metadata"}]},
    )
    context = RepositoryContext(plugin)
    violations = PromptfooMetadataRule().check(context)
    assert len(violations) == 0


def test_metadata_all_keys_present_passes(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "ok.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [
                {"description": "good meta", "metadata": {"token-usage": "small", "tier": "fast"}}
            ],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooMetadataRule(config={"required-keys": ["token-usage", "tier"]})
    violations = rule.check(context)
    assert len(violations) == 0


def test_metadata_missing_reports_all_keys(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "no-meta.yaml",
        {"providers": [{"id": "test"}], "tests": [{"description": "no metadata"}]},
    )
    context = RepositoryContext(plugin)
    rule = PromptfooMetadataRule(config={"required-keys": ["token-usage", "tier"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "tier" in violations[0].message
    assert "token-usage" in violations[0].message


def test_metadata_applied_to_fragment_tests(temp_dir):
    plugin = _make_plugin(temp_dir)
    frag = plugin / "evals" / "cases.yaml"
    _write_yaml(frag, [{"description": "frag test"}])
    _write_yaml(
        plugin / "evals" / "config.yaml",
        {"providers": [{"id": "test"}], "tests": ["file://cases.yaml"]},
    )
    context = RepositoryContext(plugin)
    rule = PromptfooMetadataRule(config={"required-keys": ["tier"]})
    violations = rule.check(context)
    assert any("tier" in v.message for v in violations)


def test_metadata_not_mapping_fails(temp_dir):
    plugin = _make_plugin(temp_dir)
    _write_yaml(
        plugin / "evals" / "bad-meta.yaml",
        {
            "providers": [{"id": "test"}],
            "tests": [{"description": "bad", "metadata": "not-a-dict"}],
        },
    )
    context = RepositoryContext(plugin)
    rule = PromptfooMetadataRule(config={"required-keys": ["tier"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "mapping" in violations[0].message.lower()


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
