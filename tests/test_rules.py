"""
Tests for builtin rules
"""

import sys
from pathlib import Path


from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.plugin_structure import (
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
    CommandsDirRequiredRule,
    CommandsExistRule,
)
from skillsaw.rules.builtin.command_format import (
    CommandNamingRule,
    CommandFrontmatterRule,
)
from skillsaw.rules.builtin.marketplace import (
    MarketplaceRegistrationRule,
)


def test_plugin_json_required_passes(valid_plugin):
    """Test that valid plugin passes plugin.json requirement"""
    context = RepositoryContext(valid_plugin)
    rule = PluginJsonRequiredRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_plugin_json_required_fails(temp_dir):
    """Test that plugin without plugin.json fails"""
    plugin_dir = temp_dir / "bad-plugin"
    plugin_dir.mkdir()

    # Create .claude-plugin dir but no plugin.json inside
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    # Create commands dir so it looks like a plugin
    (plugin_dir / "commands").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = PluginJsonRequiredRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.ERROR


def test_plugin_json_valid_passes(valid_plugin):
    """Test that valid plugin.json passes validation"""
    context = RepositoryContext(valid_plugin)
    rule = PluginJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_plugin_naming_passes(valid_plugin):
    """Test that kebab-case plugin name passes"""
    context = RepositoryContext(valid_plugin)
    rule = PluginNamingRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_command_naming_passes(valid_plugin):
    """Test that kebab-case command names pass"""
    context = RepositoryContext(valid_plugin)
    rule = CommandNamingRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_command_frontmatter_passes(valid_plugin):
    """Test that valid command frontmatter passes"""
    context = RepositoryContext(valid_plugin)
    rule = CommandFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_marketplace_registration_passes(marketplace_repo):
    """Test that registered plugins pass marketplace check"""
    context = RepositoryContext(marketplace_repo)
    rule = MarketplaceRegistrationRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_marketplace_registration_fails(marketplace_repo):
    """Test that unregistered plugin fails marketplace check"""
    # Add a plugin that's not registered
    plugins_dir = marketplace_repo / "plugins"
    new_plugin = plugins_dir / "plugin-three"
    new_plugin.mkdir()

    claude_dir = new_plugin / ".claude-plugin"
    claude_dir.mkdir()

    import json

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump(
            {
                "name": "plugin-three",
                "description": "Third plugin",
                "version": "1.0.0",
                "author": {"name": "Test"},
            },
            f,
        )

    context = RepositoryContext(marketplace_repo)
    rule = MarketplaceRegistrationRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "plugin-three" in violations[0].message


def test_plugin_json_name_only_warns_for_recommended(temp_dir):
    """Test that plugin.json with only 'name' produces warnings for recommended fields"""
    import json

    plugin_dir = temp_dir / "minimal-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "minimal-plugin"}, f)

    (plugin_dir / "commands").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule()
    violations = rule.check(context)

    # Should have 3 warnings for missing recommended fields, no errors
    assert len(violations) == 3
    for v in violations:
        assert v.severity == Severity.WARNING
        assert "recommended" in v.message

    recommended = {v.message.split("'")[1] for v in violations}
    assert recommended == {"description", "version", "author"}


def test_plugin_json_custom_recommended_fields(temp_dir):
    """Test that recommended-fields config controls which fields are checked"""
    import json

    plugin_dir = temp_dir / "minimal-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "minimal-plugin"}, f)

    (plugin_dir / "commands").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule({"recommended-fields": ["description", "version"]})
    violations = rule.check(context)

    # Should have 2 warnings (description, version) but NOT author
    assert len(violations) == 2
    for v in violations:
        assert v.severity == Severity.WARNING
        assert "recommended" in v.message

    recommended = {v.message.split("'")[1] for v in violations}
    assert recommended == {"description", "version"}


def test_plugin_json_empty_recommended_fields(temp_dir):
    """Test that empty recommended-fields disables all recommended field checks"""
    import json

    plugin_dir = temp_dir / "minimal-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "minimal-plugin"}, f)

    (plugin_dir / "commands").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule({"recommended-fields": []})
    violations = rule.check(context)

    assert len(violations) == 0


def test_plugin_json_missing_name_is_error(temp_dir):
    """Test that plugin.json missing 'name' produces an error"""
    import json

    plugin_dir = temp_dir / "no-name-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"description": "A plugin without a name"}, f)

    (plugin_dir / "commands").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule()
    violations = rule.check(context)

    errors = [v for v in violations if v.severity == Severity.ERROR]
    warnings = [v for v in violations if v.severity == Severity.WARNING]

    assert len(errors) == 1
    assert "name" in errors[0].message
    # version and author are missing -> 2 warnings
    assert len(warnings) == 2


def test_commands_dir_required_passes_with_commands(valid_plugin):
    """Test that plugin with commands/ directory passes"""
    context = RepositoryContext(valid_plugin)
    rule = CommandsDirRequiredRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_commands_dir_required_passes_with_skills(temp_dir):
    """Test that plugin with skills/ directory (no commands/) passes"""
    import json

    plugin_dir = temp_dir / "skills-only-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "skills-only-plugin"}, f)

    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "my-skill"
    skill_dir.mkdir()
    with open(skill_dir / "SKILL.md", "w") as f:
        f.write("---\ndescription: Test skill\n---\n# Test\n")

    context = RepositoryContext(plugin_dir)
    rule = CommandsDirRequiredRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_commands_dir_required_fails_without_commands_or_skills(temp_dir):
    """Test that plugin without commands/ or skills/ fails"""
    import json

    plugin_dir = temp_dir / "empty-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "empty-plugin"}, f)

    # Need agents/ so plugin is discovered (context needs a component dir)
    (plugin_dir / "agents").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = CommandsDirRequiredRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "commands or skills" in violations[0].message


def test_commands_exist_passes_with_skills_only(temp_dir):
    """Test that plugin with skills but no commands passes commands-exist"""
    import json

    plugin_dir = temp_dir / "skills-only-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "skills-only-plugin"}, f)

    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "my-skill"
    skill_dir.mkdir()
    with open(skill_dir / "SKILL.md", "w") as f:
        f.write("---\ndescription: Test skill\n---\n# Test\n")

    context = RepositoryContext(plugin_dir)
    rule = CommandsExistRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_commands_exist_fails_with_empty_dirs(temp_dir):
    """Test that plugin with empty commands/ and skills/ dirs fails"""
    import json

    plugin_dir = temp_dir / "empty-dirs-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "empty-dirs-plugin"}, f)

    (plugin_dir / "commands").mkdir()
    (plugin_dir / "skills").mkdir()

    context = RepositoryContext(plugin_dir)
    rule = CommandsExistRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "No command or skill files found" in violations[0].message
