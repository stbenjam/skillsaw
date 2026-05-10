"""
Tests for configuration management
"""

import sys
from pathlib import Path
import yaml


from skillsaw.config import LinterConfig, find_config
from skillsaw.context import (
    RepositoryContext,
    RepositoryType,
    HAS_CURSOR,
    HAS_CLAUDE_MD,
    ALL_INSTRUCTION_FORMATS,
)


def test_default_config():
    """Test default configuration"""
    config = LinterConfig.default()
    assert "plugin-json-required" in config.rules
    assert config.rules["plugin-json-required"]["enabled"] == "auto"
    assert config.rules["plugin-json-required"]["severity"] == "error"


def test_config_from_file(temp_dir):
    """Test loading configuration from file"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_data = {
        "rules": {"plugin-json-required": {"enabled": False, "severity": "warning"}},
        "strict": True,
    }

    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    config = LinterConfig.from_file(config_file)
    assert config.rules["plugin-json-required"]["enabled"] is False
    assert config.rules["plugin-json-required"]["severity"] == "warning"
    assert config.strict is True


def test_find_config(temp_dir):
    """Test config file discovery with .skillsaw.yaml"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.touch()

    subdir = temp_dir / "subdir"
    subdir.mkdir()

    found = find_config(subdir)
    assert found.resolve() == config_file.resolve()


def test_find_config_legacy_claudelint(temp_dir):
    """Test backward-compat discovery of .claudelint.yaml"""
    config_file = temp_dir / ".claudelint.yaml"
    config_file.touch()

    subdir = temp_dir / "subdir"
    subdir.mkdir()

    found = find_config(subdir)
    assert found.resolve() == config_file.resolve()


def test_find_config_prefers_skillsaw(temp_dir):
    """.skillsaw.yaml takes priority over .claudelint.yaml"""
    (temp_dir / ".skillsaw.yaml").touch()
    (temp_dir / ".claudelint.yaml").touch()

    found = find_config(temp_dir)
    assert found.name == ".skillsaw.yaml"


def test_rule_enabled_for_context(valid_plugin):
    """Test context-aware rule enabling"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig.default()

    # marketplace-registration should be disabled for single plugin
    enabled = config.is_rule_enabled(
        "marketplace-registration", context, {RepositoryType.MARKETPLACE}
    )
    assert enabled is False


def test_rule_enabled_auto(marketplace_repo):
    """Test 'auto' enabled rules"""
    context = RepositoryContext(marketplace_repo)
    config = LinterConfig.default()

    # marketplace-registration should be enabled for marketplace
    enabled = config.is_rule_enabled(
        "marketplace-registration", context, {RepositoryType.MARKETPLACE}
    )
    assert enabled is True


def test_auto_agentskills_fires_on_all_skill_repo_types(temp_dir):
    """Test that auto with agentskills repo_types fires on relevant repo types"""
    config = LinterConfig.default()
    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    # AGENTSKILLS repo
    skill = temp_dir / "skill-repo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: skill-repo\ndescription: A skill\n---\n")
    ctx = RepositoryContext(skill)
    assert ctx.repo_type == RepositoryType.AGENTSKILLS
    assert config.is_rule_enabled("agentskill-valid", ctx, repo_types) is True

    # SINGLE_PLUGIN repo
    import json

    plugin = temp_dir / "plugin-repo"
    plugin.mkdir()
    claude_dir = plugin / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(json.dumps({"name": "plugin-repo"}))
    ctx = RepositoryContext(plugin)
    assert ctx.repo_type == RepositoryType.SINGLE_PLUGIN
    assert config.is_rule_enabled("agentskill-valid", ctx, repo_types) is True

    # DOT_CLAUDE repo
    dot_claude = temp_dir / "dot-claude-repo"
    dot_claude.mkdir()
    dc = dot_claude / ".claude"
    dc.mkdir()
    (dc / "commands").mkdir()
    ctx = RepositoryContext(dot_claude)
    assert ctx.repo_type == RepositoryType.DOT_CLAUDE
    assert config.is_rule_enabled("agentskill-valid", ctx, repo_types) is True

    # UNKNOWN repo
    empty = temp_dir / "empty-repo"
    empty.mkdir()
    ctx = RepositoryContext(empty)
    assert ctx.repo_type == RepositoryType.UNKNOWN
    assert config.is_rule_enabled("agentskill-valid", ctx, repo_types) is False


def test_save_no_trailing_whitespace(tmp_path):
    """Test that saved config has no trailing whitespace and is valid YAML"""
    config = LinterConfig.default()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()

    # Every line must be free of trailing whitespace
    for i, line in enumerate(content.splitlines(), start=1):
        assert line == line.rstrip(), f"Line {i} has trailing whitespace: {line!r}"

    # The output must be valid YAML
    parsed = yaml.safe_load(content)
    assert parsed is not None
    assert "rules" in parsed

    # Verify the block-style list round-trips correctly
    plugin_json_valid = parsed["rules"]["plugin-json-valid"]
    assert plugin_json_valid["recommended-fields"] == [
        "description",
        "version",
        "author",
    ]


def test_auto_without_repo_types_always_enabled(valid_plugin):
    """Test that auto with repo_types=None enables for any repo type"""
    config = LinterConfig.default()
    context = RepositoryContext(valid_plugin)
    assert config.is_rule_enabled("some-rule", context, None) is True


def test_auto_with_formats_enabled_when_format_detected(temp_dir):
    """Test that auto with formats fires when the format is detected"""
    (temp_dir / ".cursor" / "rules").mkdir(parents=True)
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={"test-rule": {"enabled": "auto"}})
    assert config.is_rule_enabled("test-rule", context, None, {HAS_CURSOR}) is True


def test_auto_with_formats_disabled_when_format_missing(temp_dir):
    """Test that auto with formats does not fire when format is absent"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={"test-rule": {"enabled": "auto"}})
    assert config.is_rule_enabled("test-rule", context, None, {HAS_CURSOR}) is False


def test_auto_with_formats_or_repo_types(temp_dir):
    """Test that either repo_types or formats match enables the rule"""
    (temp_dir / "CLAUDE.md").write_text("# Instructions")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={"test-rule": {"enabled": "auto"}})
    assert (
        config.is_rule_enabled(
            "test-rule",
            context,
            {RepositoryType.MARKETPLACE},
            ALL_INSTRUCTION_FORMATS,
        )
        is True
    )


def test_auto_with_formats_and_repo_types_both_miss(temp_dir):
    """Test that rule is disabled when neither repo_types nor formats match"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={"test-rule": {"enabled": "auto"}})
    assert (
        config.is_rule_enabled(
            "test-rule",
            context,
            {RepositoryType.MARKETPLACE},
            {HAS_CURSOR},
        )
        is False
    )


def test_explicit_enabled_overrides_auto_detection(temp_dir):
    """Test that explicit enabled: true/false in config overrides auto"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={"test-rule": {"enabled": False}})
    assert config.is_rule_enabled("test-rule", context, None, {HAS_CURSOR}) is False

    config2 = LinterConfig(rules={"test-rule": {"enabled": True}})
    assert config2.is_rule_enabled("test-rule", context, None, {HAS_CURSOR}) is True


def test_format_specific_rules_default_to_auto():
    """Test that instruction file rules now default to auto"""
    config = LinterConfig.default()
    auto_rules = [
        "instruction-file-valid",
        "instruction-imports-valid",
    ]
    for rule_id in auto_rules:
        assert config.rules[rule_id]["enabled"] == "auto", f"{rule_id} should be auto"


def test_content_rules_default_to_auto():
    """Test that content intelligence rules now default to auto"""
    config = LinterConfig.default()
    content_rules = [
        "content-weak-language",
        "content-tautological",
        "content-critical-position",
        "content-redundant-with-tooling",
        "content-instruction-budget",
        "content-negative-only",
        "content-section-length",
        "content-contradiction",
        "content-hook-candidate",
        "content-actionability-score",
        "content-cognitive-chunks",
        "content-embedded-secrets",
        "content-banned-references",
        "content-inconsistent-terminology",
    ]
    for rule_id in content_rules:
        assert config.rules[rule_id]["enabled"] == "auto", f"{rule_id} should be auto"


def test_default_config_sets_current_version():
    """No config file means all rules run — version must be current release"""
    from skillsaw import __version__

    config = LinterConfig.default()
    assert config.version == __version__


def test_no_config_skips_version_gate(temp_dir):
    """Without a config file, version-gated rules should still be enabled"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig.default()
    assert config.is_rule_enabled(
        "content-weak-language",
        context,
        repo_types=None,
        formats=frozenset({"HAS_CLAUDE_MD"}),
        since_version="0.7.0",
    )


def test_for_init_sets_version():
    """Test that for_init() sets version to current release"""
    from skillsaw import __version__

    init_config = LinterConfig.for_init()
    assert init_config.version == __version__
    assert init_config.rules == LinterConfig.default().rules


def test_version_from_file_defaults_to_0_6(tmp_path):
    """Config files without a version key are treated as 0.6.0"""
    config_file = tmp_path / ".skillsaw.yaml"
    config_file.write_text("rules: {}\n")
    config = LinterConfig.from_file(config_file)
    assert config.version == "0.6.0"


def test_version_from_file_explicit(tmp_path):
    """Config files with an explicit version are parsed correctly"""
    config_file = tmp_path / ".skillsaw.yaml"
    config_file.write_text('version: "0.7.0"\nrules: {}\n')
    config = LinterConfig.from_file(config_file)
    assert config.version == "0.7.0"


def test_version_gates_new_rules(temp_dir):
    """Rules with since > config version are skipped"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.6.0",
        rules={"content-weak-language": {"enabled": "auto"}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is False
    )


def test_version_allows_matching_rules(temp_dir):
    """Rules with since <= config version pass the gate"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.7.0",
        rules={"content-weak-language": {"enabled": "auto"}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is True
    )


def test_explicit_true_overrides_version_gate(temp_dir):
    """Explicit enabled: true bypasses version gating"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.6.0",
        rules={"content-weak-language": {"enabled": True}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is True
    )


def test_explicit_false_overrides_version(temp_dir):
    """Explicit enabled: false is honored regardless of version"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.7.0",
        rules={"content-weak-language": {"enabled": False}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is False
    )


def test_no_version_means_all_rules_active(temp_dir):
    """No config version (empty string) means all rules are active"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="",
        rules={"content-weak-language": {"enabled": "auto"}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is True
    )


def test_severity_override_bypasses_version_gate(temp_dir):
    """Configuring a rule's severity implies the user wants it active"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.6.0",
        rules={"content-weak-language": {"severity": "error"}},
    )
    assert (
        config.is_rule_enabled(
            "content-weak-language",
            context,
            formats=ALL_INSTRUCTION_FORMATS,
            since_version="0.7.0",
        )
        is True
    )


def test_save_includes_version(tmp_path):
    """Test that save() writes the version field"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)
    parsed = yaml.safe_load(config_path.read_text())
    assert "version" in parsed
    assert parsed["version"] == config.version


# --- Null/wrong-type YAML config field tests ---


def test_null_rules_does_not_crash(temp_dir):
    """rules: null should not crash, should behave like empty dict"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules:\n")  # YAML parses bare key as None

    config = LinterConfig.from_file(config_file)
    assert config.rules == {}


def test_null_custom_rules_does_not_crash(temp_dir):
    """custom-rules: null should not crash, should behave like empty list"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("custom-rules:\n")

    config = LinterConfig.from_file(config_file)
    assert config.custom_rules == []


def test_null_exclude_does_not_crash(temp_dir):
    """exclude: null should not crash, should behave like empty list"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("exclude:\n")

    config = LinterConfig.from_file(config_file)
    assert config.exclude_patterns == []


def test_null_strict_does_not_crash(temp_dir):
    """strict: null should not crash, should behave like False"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("strict:\n")

    config = LinterConfig.from_file(config_file)
    assert config.strict is False


def test_explicit_null_rules(temp_dir):
    """rules: null (explicit) should not crash"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules: null\n")

    config = LinterConfig.from_file(config_file)
    assert config.rules == {}


def test_rules_as_list_raises_error(temp_dir):
    """rules as a list instead of dict should raise a clear ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules:\n  - plugin-json-required\n  - plugin-naming\n")

    import pytest

    with pytest.raises(ValueError, match="'rules' must be a mapping"):
        LinterConfig.from_file(config_file)


def test_custom_rules_wrong_type_raises_error(temp_dir):
    """custom-rules as a string should raise a clear ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text('custom-rules: "my_rule.py"\n')

    import pytest

    with pytest.raises(ValueError, match="'custom-rules' must be a list"):
        LinterConfig.from_file(config_file)


def test_exclude_wrong_type_raises_error(temp_dir):
    """exclude as a string should raise a clear ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text('exclude: "*.pyc"\n')

    import pytest

    with pytest.raises(ValueError, match="'exclude' must be a list"):
        LinterConfig.from_file(config_file)


def test_null_rule_config_value(temp_dir):
    """A rule key with null value should not crash get_rule_config"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules:\n  plugin-json-required:\n")

    config = LinterConfig.from_file(config_file)
    # Should not crash; null rule config treated as empty override
    rule_config = config.get_rule_config("plugin-json-required")
    # Should still get defaults
    assert "enabled" in rule_config


def test_all_fields_null_does_not_crash(temp_dir):
    """Config with every field set to null should load without crashing"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules:\ncustom-rules:\nexclude:\nstrict:\n")

    config = LinterConfig.from_file(config_file)
    assert config.rules == {}
    assert config.custom_rules == []
    assert config.exclude_patterns == []
    assert config.strict is False
