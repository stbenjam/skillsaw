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
        "content-dead-references",
        "content-tautological",
        "content-critical-position",
        "content-redundant-with-tooling",
        "content-instruction-budget",
        "content-readme-overlap",
        "content-negative-only",
        "content-section-length",
        "content-contradiction",
        "content-hook-candidate",
        "content-actionability-score",
        "content-cognitive-chunks",
        "content-embedded-secrets",
        "content-cross-file-consistency",
    ]
    for rule_id in content_rules:
        assert config.rules[rule_id]["enabled"] == "auto", f"{rule_id} should be auto"


def test_for_init_equals_default():
    """Test that for_init() returns same config as default() now that all rules are auto"""
    init_config = LinterConfig.for_init()
    default_config = LinterConfig.default()
    assert init_config.rules == default_config.rules
