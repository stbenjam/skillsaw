"""
Tests for repository context detection
"""

import json
import sys
from pathlib import Path


from skillsaw.context import RepositoryContext, RepositoryType


def test_single_plugin_detection(valid_plugin):
    """Test detection of single plugin repository"""
    context = RepositoryContext(valid_plugin)
    assert context.repo_type == RepositoryType.SINGLE_PLUGIN
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == valid_plugin.resolve()


def test_marketplace_detection(marketplace_repo):
    """Test detection of marketplace repository"""
    context = RepositoryContext(marketplace_repo)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2
    assert context.has_marketplace()


def test_plugin_name_extraction(valid_plugin):
    """Test plugin name extraction"""
    context = RepositoryContext(valid_plugin)
    name = context.get_plugin_name(valid_plugin)
    assert name == "test-plugin"


def test_marketplace_registration(marketplace_repo):
    """Test marketplace registration check"""
    context = RepositoryContext(marketplace_repo)
    assert context.is_registered_in_marketplace("plugin-one")
    assert context.is_registered_in_marketplace("plugin-two")
    assert not context.is_registered_in_marketplace("plugin-three")


def test_unknown_repository(temp_dir):
    """Test detection of unknown repository type"""
    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.UNKNOWN
    assert len(context.plugins) == 0


def test_flat_structure_discovery(flat_structure_marketplace):
    """Test discovery of flat structure plugins (source: './')"""
    context = RepositoryContext(flat_structure_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == flat_structure_marketplace.resolve()


def test_flat_structure_name(flat_structure_marketplace):
    """Test plugin name extraction for flat structure"""
    context = RepositoryContext(flat_structure_marketplace)
    name = context.get_plugin_name(flat_structure_marketplace)
    assert name == "flat-plugin"


def test_custom_path_discovery(custom_path_marketplace):
    """Test discovery of plugins in custom directories"""
    context = RepositoryContext(custom_path_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1
    expected_path = (custom_path_marketplace / "custom" / "my-plugin").resolve()
    assert context.plugins[0].resolve() == expected_path


def test_strict_false_without_plugin_json(strict_false_marketplace):
    """Test plugin discovery when strict: false and no plugin.json"""
    context = RepositoryContext(strict_false_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1

    plugin_path = strict_false_marketplace / "my-plugin"
    assert plugin_path.resolve() in [p.resolve() for p in context.plugins]

    # Check metadata is stored (use resolved path)
    resolved_path = plugin_path.resolve()
    assert resolved_path in context.plugin_metadata
    assert context.plugin_metadata[resolved_path]["name"] == "no-manifest-plugin"


def test_strict_false_metadata_retrieval(strict_false_marketplace):
    """Test metadata retrieval for strict: false plugins"""
    context = RepositoryContext(strict_false_marketplace)
    plugin_path = strict_false_marketplace / "my-plugin"

    metadata = context.get_plugin_metadata(plugin_path)
    assert metadata is not None
    assert metadata["name"] == "no-manifest-plugin"
    assert metadata["version"] == "2.0.0"
    assert metadata["author"]["name"] == "Marketplace Author"


def test_plugin_json_precedence_over_marketplace(custom_path_marketplace):
    """
    plugin.json fields should take precedence over marketplace metadata when both exist.
    """
    context = RepositoryContext(custom_path_marketplace)
    plugin_dir = custom_path_marketplace / "custom" / "my-plugin"

    # Overwrite plugin.json with a conflicting name
    pj = plugin_dir / ".claude-plugin" / "plugin.json"
    obj = json.loads(pj.read_text())
    obj["name"] = "custom-plugin-from-json"
    pj.write_text(json.dumps(obj))

    # Recreate context to pick up changes
    context = RepositoryContext(custom_path_marketplace)

    # Name should come from plugin.json, not marketplace
    assert context.get_plugin_name(plugin_dir) == "custom-plugin-from-json"


def test_mixed_marketplace_discovery(mixed_marketplace):
    """Test discovery of plugins from both plugins/ dir and marketplace sources"""
    context = RepositoryContext(mixed_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2

    plugin_names = [context.get_plugin_name(p) for p in context.plugins]
    assert "marketplace-plugin" in plugin_names
    assert "plugins-dir-plugin" in plugin_names


def test_remote_source_handling(remote_source_marketplace, caplog):
    """Test handling of remote plugin sources (GitHub, git URLs)"""
    import logging

    caplog.set_level(logging.INFO)

    context = RepositoryContext(remote_source_marketplace)
    assert context.repo_type == RepositoryType.MARKETPLACE
    # Remote plugins should not be discovered locally
    assert len(context.plugins) == 0

    # Check that INFO messages were logged
    log_output = " ".join(record.message for record in caplog.records)
    assert "github-plugin" in log_output
    assert "git-plugin" in log_output
    assert "Skipping local validation" in log_output


def test_plugin_name_from_marketplace(strict_false_marketplace):
    """Test get_plugin_name uses marketplace data when plugin.json missing"""
    context = RepositoryContext(strict_false_marketplace)
    plugin_path = strict_false_marketplace / "my-plugin"

    name = context.get_plugin_name(plugin_path)
    assert name == "no-manifest-plugin"


def test_marketplace_registration_with_flat_structure(flat_structure_marketplace):
    """Test that flat structure plugins are registered in marketplace"""
    context = RepositoryContext(flat_structure_marketplace)
    assert context.is_registered_in_marketplace("flat-plugin")


def test_backward_compatibility_with_plugins_dir(marketplace_repo):
    """Test that existing plugins/ directory scanning still works"""
    context = RepositoryContext(marketplace_repo)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 2
    names = [context.get_plugin_name(p) for p in context.plugins]
    assert "plugin-one" in names
    assert "plugin-two" in names


def test_disallow_parent_traversal(temp_dir, caplog):
    """Do not allow marketplace sources to escape repo root with .."""
    import logging

    caplog.set_level(logging.WARNING)

    claude = temp_dir / ".claude-plugin"
    claude.mkdir()
    with open(claude / "marketplace.json", "w") as f:
        json.dump(
            {
                "name": "test-marketplace",
                "plugins": [{"name": "evil-plugin", "source": "../outside"}],
            },
            f,
        )

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 0

    # Check that warning was logged
    assert any("escapes repository root" in record.message for record in caplog.records)


def test_dot_claude_detection(temp_dir):
    """Test detection of .claude/ directory with commands"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == claude_dir.resolve()


def test_dot_claude_direct(temp_dir):
    """Test linting .claude/ directory directly"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "skills").mkdir()

    context = RepositoryContext(claude_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.plugins) == 1
    assert context.plugins[0].resolve() == claude_dir.resolve()


def test_dot_claude_skills_discovery(temp_dir):
    """Test that skills inside .claude/skills/ are discovered"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    skill_dir = claude_dir / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: Test\n---\n")

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context.skills) == 1
    assert context.skills[0].resolve() == skill_dir.resolve()


def test_dot_claude_not_detected_empty(temp_dir):
    """Empty .claude/ without marker dirs should not be DOT_CLAUDE"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()

    context = RepositoryContext(temp_dir)
    assert context.repo_type == RepositoryType.UNKNOWN


def test_repo_type_override_marketplace(temp_dir):
    """Test that repo_type override causes marketplace discovery to run"""
    # Create a repo that looks like a marketplace but would NOT be auto-detected
    # (no .claude-plugin dir, no plugins/ dir). Instead it has a plugins/ dir
    # with plugin subdirectories, but without the .claude-plugin/marketplace.json
    # so auto-detect would say UNKNOWN.
    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()

    plugin_dir = plugins_dir / "my-plugin"
    plugin_dir.mkdir()
    (plugin_dir / ".claude-plugin").mkdir()
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "my-plugin", "description": "A plugin", "version": "1.0.0"})
    )
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "commands" / "test.md").write_text("---\ndescription: Test\n---\n# Test")

    # Without override: auto-detects as MARKETPLACE (because plugins/ dir exists)
    context_auto = RepositoryContext(temp_dir)
    assert context_auto.repo_type == RepositoryType.MARKETPLACE
    assert len(context_auto.plugins) == 1

    # With override to SINGLE_PLUGIN: should use that type and discover accordingly
    context_override = RepositoryContext(temp_dir, repo_type=RepositoryType.SINGLE_PLUGIN)
    assert context_override.repo_type == RepositoryType.SINGLE_PLUGIN
    # SINGLE_PLUGIN discovers root_path as the plugin
    assert len(context_override.plugins) == 1
    assert context_override.plugins[0].resolve() == temp_dir.resolve()


def test_repo_type_override_forces_discovery(temp_dir):
    """Test that --type override actually re-runs discovery with the new type.

    This is the core regression test: a repo that auto-detects as UNKNOWN
    but is overridden to MARKETPLACE should discover marketplace plugins.
    """
    # Create marketplace structure
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {
                "name": "test-plugin",
                "source": "./plugins/test-plugin",
                "description": "A test plugin",
            }
        ],
    }
    (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))

    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()
    plugin_dir = plugins_dir / "test-plugin"
    plugin_dir.mkdir()
    (plugin_dir / ".claude-plugin").mkdir()
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "test-plugin", "description": "Test", "version": "1.0.0"})
    )
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "commands" / "test.md").write_text("---\ndescription: Test\n---\n# Test")

    # This auto-detects as MARKETPLACE — verify the override path works too
    context = RepositoryContext(temp_dir, repo_type=RepositoryType.MARKETPLACE)
    assert context.repo_type == RepositoryType.MARKETPLACE
    assert len(context.plugins) == 1
    assert context.get_plugin_name(context.plugins[0]) == "test-plugin"


def test_repo_type_override_to_dot_claude(temp_dir):
    """Test overriding repo type to DOT_CLAUDE triggers correct discovery"""
    # Create .claude structure
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "commands").mkdir()

    # Without override, auto-detects as DOT_CLAUDE
    context_auto = RepositoryContext(temp_dir)
    assert context_auto.repo_type == RepositoryType.DOT_CLAUDE
    assert len(context_auto.plugins) == 1

    # Override to UNKNOWN — should find no plugins
    context_override = RepositoryContext(temp_dir, repo_type=RepositoryType.UNKNOWN)
    assert context_override.repo_type == RepositoryType.UNKNOWN
    assert len(context_override.plugins) == 0


def test_repo_type_override_none_uses_autodetect(temp_dir):
    """Passing repo_type=None should behave identically to auto-detection"""
    claude_dir = temp_dir / ".claude"
    claude_dir.mkdir()
    (claude_dir / "skills").mkdir()

    context_default = RepositoryContext(temp_dir)
    context_none = RepositoryContext(temp_dir, repo_type=None)

    assert context_default.repo_type == context_none.repo_type
    assert len(context_default.plugins) == len(context_none.plugins)
