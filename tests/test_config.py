"""
Tests for configuration management
"""

import sys
from pathlib import Path
import yaml


from agentlint.config import LinterConfig, find_config
from agentlint.context import RepositoryContext, RepositoryType


def test_default_config():
    """Test default configuration"""
    config = LinterConfig.default()
    assert "plugin-json-required" in config.rules
    assert config.rules["plugin-json-required"]["enabled"] is True
    assert config.rules["plugin-json-required"]["severity"] == "error"


def test_config_from_file(temp_dir):
    """Test loading configuration from file"""
    config_file = temp_dir / ".agentlint.yaml"
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
    """Test config file discovery with .agentlint.yaml"""
    config_file = temp_dir / ".agentlint.yaml"
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


def test_find_config_prefers_agentlint(temp_dir):
    """.agentlint.yaml takes priority over .claudelint.yaml"""
    (temp_dir / ".agentlint.yaml").touch()
    (temp_dir / ".claudelint.yaml").touch()

    found = find_config(temp_dir)
    assert found.name == ".agentlint.yaml"


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
    """Test that auto with agentskills repo_types fires on AGENTSKILLS, PLUGIN, MARKETPLACE"""
    config = LinterConfig.default()
    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
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

    # UNKNOWN repo
    empty = temp_dir / "empty-repo"
    empty.mkdir()
    ctx = RepositoryContext(empty)
    assert ctx.repo_type == RepositoryType.UNKNOWN
    assert config.is_rule_enabled("agentskill-valid", ctx, repo_types) is False


def test_auto_without_repo_types_always_enabled(valid_plugin):
    """Test that auto with repo_types=None enables for any repo type"""
    config = LinterConfig.default()
    context = RepositoryContext(valid_plugin)
    assert config.is_rule_enabled("some-rule", context, None) is True
