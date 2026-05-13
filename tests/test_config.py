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


def test_default_exclude_patterns():
    """Test that default config includes sensible exclude patterns for templates"""
    config = LinterConfig.default()
    assert "**/template/**" in config.exclude_patterns
    assert "**/templates/**" in config.exclude_patterns
    assert "**/_template/**" in config.exclude_patterns


def test_default_exclude_patterns_not_empty():
    """Test that default exclude patterns list is non-empty"""
    config = LinterConfig.default()
    assert len(config.exclude_patterns) >= 3


def test_user_exclude_overrides_defaults(temp_dir):
    """User-specified exclude patterns in config file override the defaults"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_data = {
        "exclude": ["my-custom-exclude/**"],
    }
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)
    config = LinterConfig.from_file(config_file)
    assert config.exclude_patterns == ["my-custom-exclude/**"]
    assert "**/template/**" not in config.exclude_patterns


def test_for_init_includes_default_excludes():
    """for_init() should also include the default exclude patterns"""
    config = LinterConfig.for_init()
    assert "**/template/**" in config.exclude_patterns
    assert "**/templates/**" in config.exclude_patterns


def test_from_file_applies_default_excludes(temp_dir):
    """Omitting 'exclude' from config file should apply default patterns"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules: {}\n")
    config = LinterConfig.from_file(config_file)
    assert "**/template/**" in config.exclude_patterns
    assert "**/templates/**" in config.exclude_patterns
    assert "**/_template/**" in config.exclude_patterns


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
    """Rules with since > config version are skipped when not explicitly configured"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    # No user overrides for this rule — version gate should block it
    config = LinterConfig(version="0.6.0", rules={})
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


def test_explicit_auto_overrides_version_gate(temp_dir):
    """Explicit enabled: auto in user config bypasses version gating"""
    (temp_dir / "CLAUDE.md").write_text("# Test")
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        version="0.6.0",
        rules={"content-weak-language": {"enabled": "auto"}},
    )
    # The user explicitly set enabled: auto, so the version gate should
    # not block the rule even though config version < since_version.
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
    """exclude: null should not crash, should apply defaults"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("exclude:\n")

    config = LinterConfig.from_file(config_file)
    assert "**/template/**" in config.exclude_patterns


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
    assert "**/template/**" in config.exclude_patterns
    assert config.strict is False


# --- Falsey wrong-type regression tests ---


def test_rules_empty_list_raises_error(temp_dir):
    """rules: [] (falsey but wrong type) should raise ValueError, not silently become {}"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules: []\n")

    import pytest

    with pytest.raises(ValueError, match="'rules' must be a mapping"):
        LinterConfig.from_file(config_file)


def test_custom_rules_empty_string_raises_error(temp_dir):
    """custom-rules: '' (falsey but wrong type) should raise ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("custom-rules: ''\n")

    import pytest

    with pytest.raises(ValueError, match="'custom-rules' must be a list"):
        LinterConfig.from_file(config_file)


def test_exclude_empty_string_raises_error(temp_dir):
    """exclude: '' (falsey but wrong type) should raise ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("exclude: ''\n")

    import pytest

    with pytest.raises(ValueError, match="'exclude' must be a list"):
        LinterConfig.from_file(config_file)


def test_strict_string_raises_error(temp_dir):
    """strict: 'false' (string, not bool) should raise ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("strict: 'false'\n")

    import pytest

    with pytest.raises(ValueError, match="'strict' must be a boolean"):
        LinterConfig.from_file(config_file)


def test_rule_config_non_mapping_raises_error(temp_dir):
    """rules: {plugin-json-required: true} should raise ValueError"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules:\n  plugin-json-required: true\n")

    import pytest

    with pytest.raises(ValueError, match="'rules.plugin-json-required' must be a mapping or null"):
        LinterConfig.from_file(config_file)


# --- Non-enabled config overrides tests ---


def test_severity_override_enables_disabled_rule(temp_dir):
    """Setting severity on a disabled-by-default rule should implicitly enable it"""
    context = RepositoryContext(temp_dir)
    # mcp-prohibited defaults to enabled: false
    config = LinterConfig(
        rules={"mcp-prohibited": {"severity": "error"}},
    )
    assert config.is_rule_enabled("mcp-prohibited", context) is True


def test_non_enabled_override_enables_disabled_rule(temp_dir):
    """Any non-enabled override on a disabled-by-default rule should enable it"""
    context = RepositoryContext(temp_dir)
    # agentskill-structure defaults to enabled: false
    config = LinterConfig(
        rules={"agentskill-structure": {"severity": "warning"}},
    )
    assert config.is_rule_enabled("agentskill-structure", context) is True


def test_explicit_enabled_false_still_disables(temp_dir):
    """Explicit enabled: false must still win even when other overrides are present"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        rules={"mcp-prohibited": {"enabled": False, "severity": "error"}},
    )
    assert config.is_rule_enabled("mcp-prohibited", context) is False


def test_explicit_enabled_true_with_overrides(temp_dir):
    """Explicit enabled: true with other overrides should stay enabled"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(
        rules={"mcp-prohibited": {"enabled": True, "severity": "error"}},
    )
    assert config.is_rule_enabled("mcp-prohibited", context) is True


def test_no_overrides_disabled_rule_stays_disabled(temp_dir):
    """A disabled-by-default rule with no user overrides stays disabled"""
    context = RepositoryContext(temp_dir)
    config = LinterConfig(rules={})
    assert config.is_rule_enabled("mcp-prohibited", context) is False


def test_all_disabled_default_rules_enabled_by_severity(temp_dir):
    """All rules that default to enabled: false should be activated by a severity override"""
    context = RepositoryContext(temp_dir)
    disabled_rules = [
        "mcp-prohibited",
        "agentskill-structure",
        "agentskill-evals-required",
    ]
    for rule_id in disabled_rules:
        config = LinterConfig(
            rules={rule_id: {"severity": "error"}},
        )
        assert (
            config.is_rule_enabled(rule_id, context) is True
        ), f"{rule_id} should be enabled when severity is overridden"


def test_explicit_enabled_auto_with_matching_repo(marketplace_repo):
    """Explicit enabled: auto should still work with matching repo types"""
    context = RepositoryContext(marketplace_repo)
    config = LinterConfig(
        rules={"marketplace-registration": {"enabled": "auto"}},
    )
    assert (
        config.is_rule_enabled("marketplace-registration", context, {RepositoryType.MARKETPLACE})
        is True
    )


def test_explicit_enabled_auto_with_non_matching_repo(valid_plugin):
    """Explicit enabled: auto should not fire when repo type doesn't match"""
    context = RepositoryContext(valid_plugin)
    config = LinterConfig(
        rules={"marketplace-registration": {"enabled": "auto"}},
    )
    assert (
        config.is_rule_enabled("marketplace-registration", context, {RepositoryType.MARKETPLACE})
        is False
    )


def test_severity_override_on_auto_rule_respects_repo_type(valid_plugin):
    """Overriding severity on an 'auto' rule should not bypass repo type checks"""
    context = RepositoryContext(valid_plugin)
    # marketplace-registration is enabled: "auto" for MARKETPLACE repos.
    # valid_plugin is SINGLE_PLUGIN.
    config = LinterConfig(
        rules={"marketplace-registration": {"severity": "warning"}},
    )
    assert (
        config.is_rule_enabled("marketplace-registration", context, {RepositoryType.MARKETPLACE})
        is False
    )


def test_severity_override_on_auto_rule_still_fires_when_matching(marketplace_repo):
    """Overriding severity on an 'auto' rule should still fire when repo type matches"""
    context = RepositoryContext(marketplace_repo)
    config = LinterConfig(
        rules={"marketplace-registration": {"severity": "warning"}},
    )
    assert (
        config.is_rule_enabled("marketplace-registration", context, {RepositoryType.MARKETPLACE})
        is True
    )


# --- Generated config documentation tests ---


def test_save_includes_description_comments(tmp_path):
    """Test that save() writes description comments for each rule"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()

    # Check a few known rule descriptions appear as comments
    assert "# Plugin must have .claude-plugin/plugin.json" in content
    assert "# SKILL.md files should have frontmatter with name and description" in content
    assert "# Detect potential API keys, tokens, and passwords in instruction files" in content


def test_save_includes_config_schema_as_comments(tmp_path):
    """Test that save() writes config_schema options as commented-out lines"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()

    # content-banned-references has config_schema with 'banned' and 'skip-builtins'
    # These should appear as commented-out options since they are not in the default config
    assert "    # banned: []\n" in content
    assert "    # skip-builtins: false\n" in content

    # mcp-prohibited has 'allowlist' in config_schema
    assert "    # allowlist: []\n" in content


def test_save_does_not_duplicate_existing_config_keys(tmp_path):
    """Config keys already in the rule config should not also appear as comments"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()

    # content-critical-position already has min-lines: 50 in its default config.
    # It should NOT also appear as a commented-out option.
    assert "    min-lines: 50\n" in content
    assert "    # min-lines:" not in content

    # plugin-json-valid already has recommended-fields in its default config
    assert "    # recommended-fields:" not in content


def test_save_no_schema_comments_for_rules_without_schema(tmp_path):
    """Rules without config_schema should only get a description comment"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()
    lines = content.split("\n")

    # Find the plugin-naming rule block (has no config_schema)
    plugin_naming_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "plugin-naming:":
            plugin_naming_idx = i
            break

    assert plugin_naming_idx is not None, "plugin-naming rule not found in output"

    # The line before should be a description comment
    assert lines[plugin_naming_idx - 1].strip().startswith("# Plugin names should")

    # The lines after should be the config keys (enabled, severity) and then
    # either a blank line, another description comment, or the next rule --
    # but NOT a commented-out config_schema parameter
    for j in range(plugin_naming_idx + 1, len(lines)):
        line = lines[j].strip()
        if not line or not line.startswith("#"):
            break
        # A comment without ":" is a description comment, not a config key
        if line.startswith("# ") and ":" not in line:
            break
        # Should not reach a commented-out param like "# some-key: value"
        assert False, f"Unexpected commented-out config option for plugin-naming: {line}"


def test_save_with_config_schema_is_valid_yaml(tmp_path):
    """The generated config with schema comments must still be valid YAML"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()
    parsed = yaml.safe_load(content)
    assert parsed is not None
    assert "rules" in parsed

    # Commented-out lines should not affect YAML parsing
    assert "content-banned-references" in parsed["rules"]
    assert "mcp-prohibited" in parsed["rules"]


def test_save_multiline_schema_defaults_commented(tmp_path):
    """Config schema options with complex defaults should have each line commented"""
    config = LinterConfig.for_init()
    config_path = tmp_path / ".skillsaw.yaml"
    config.save(config_path)

    content = config_path.read_text()

    # context-budget has a 'limits' config_schema with a complex dict default.
    # Each line of the multi-line value should be commented out.
    assert "    # limits:\n" in content

    # The file should still be valid YAML (multi-line comments don't break parsing)
    parsed = yaml.safe_load(content)
    assert parsed is not None
