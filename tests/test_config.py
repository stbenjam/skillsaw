"""
Tests for configuration management
"""

import sys
from pathlib import Path
import yaml


from skillsaw.config import LinterConfig, find_config
from skillsaw.context import RepositoryContext, RepositoryType


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


def test_config_null_rules_key(temp_dir):
    """Test that a config with rules: null or bare rules: does not crash"""
    # Explicit YAML null
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("rules: null\n")
    config = LinterConfig.from_file(config_file)
    assert config.rules == {}
    # Ensure downstream methods work without AttributeError
    rule_config = config.get_rule_config("plugin-json-required")
    assert rule_config["enabled"] == "auto"

    # Bare key (also YAML null)
    config_file.write_text("rules:\n")
    config = LinterConfig.from_file(config_file)
    assert config.rules == {}
    rule_config = config.get_rule_config("plugin-json-required")
    assert rule_config["enabled"] == "auto"


def test_config_null_custom_rules_and_exclude(temp_dir):
    """Test that null custom-rules and exclude keys do not crash"""
    config_file = temp_dir / ".skillsaw.yaml"
    config_file.write_text("custom-rules: null\nexclude: null\n")
    config = LinterConfig.from_file(config_file)
    assert config.custom_rules == []
    assert config.exclude_patterns == []
