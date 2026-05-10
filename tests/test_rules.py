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
)
from skillsaw.rules.builtin.command_format import (
    CommandNamingRule,
    CommandFrontmatterRule,
    CommandNameFormatRule,
)
from skillsaw.rules.builtin.skills import SkillFrontmatterRule
from skillsaw.rules.builtin.marketplace import (
    MarketplaceJsonValidRule,
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


def test_plugin_json_valid_version_rejects_trailing_garbage(temp_dir):
    """Test that version strings with trailing garbage are rejected"""
    import json

    invalid_versions = [
        "1.0.0garbage",
        "1.0.0.0.0",
        "1.0.0; rm -rf /",
        "1.0.0 ",
        "1.0.0!",
    ]

    for i, bad_version in enumerate(invalid_versions):
        plugin_dir = temp_dir / f"ver-plugin-invalid-{i}"
        plugin_dir.mkdir(exist_ok=True)

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir(exist_ok=True)

        with open(claude_dir / "plugin.json", "w") as f:
            json.dump(
                {
                    "name": "ver-plugin",
                    "description": "Test",
                    "version": bad_version,
                    "author": {"name": "Test"},
                },
                f,
            )

        (plugin_dir / "commands").mkdir(exist_ok=True)

        context = RepositoryContext(plugin_dir)
        rule = PluginJsonValidRule()
        violations = rule.check(context)

        version_violations = [
            v for v in violations if "semver" in v.message.lower() or "Version" in v.message
        ]
        assert len(version_violations) == 1, f"Expected version '{bad_version}' to be rejected"


def test_plugin_json_valid_version_accepts_semver_prerelease(temp_dir):
    """Test that valid semver versions with prerelease/build metadata are accepted"""
    import json

    valid_versions = [
        "1.0.0",
        "0.1.0",
        "10.20.30",
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha-1",
        "1.0.0-0.3.7",
        "1.0.0+build.123",
        "1.0.0+build-meta.123",
        "1.0.0-beta+build.456",
    ]

    for i, good_version in enumerate(valid_versions):
        plugin_dir = temp_dir / f"ver-plugin-valid-{i}"
        plugin_dir.mkdir(exist_ok=True)

        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir(exist_ok=True)

        with open(claude_dir / "plugin.json", "w") as f:
            json.dump(
                {
                    "name": "ver-plugin",
                    "description": "Test",
                    "version": good_version,
                    "author": {"name": "Test"},
                },
                f,
            )

        (plugin_dir / "commands").mkdir(exist_ok=True)

        context = RepositoryContext(plugin_dir)
        rule = PluginJsonValidRule()
        violations = rule.check(context)

        version_violations = [
            v for v in violations if "semver" in v.message.lower() or "Version" in v.message
        ]
        assert len(version_violations) == 0, f"Expected version '{good_version}' to be accepted"


def test_command_name_format_reports_line_number(temp_dir):
    """CommandNameFormatRule should report the line of the ## Name heading"""
    import json

    plugin_dir = temp_dir / "my-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "my-plugin"}, f)

    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    (commands_dir / "do-thing.md").write_text(
        "---\ndescription: Does a thing\n---\n\n## Name\nwrong-name:do-thing\n\n## Synopsis\nUsage\n"
    )

    context = RepositoryContext(plugin_dir)
    violations = CommandNameFormatRule().check(context)
    assert len(violations) == 1
    assert "my-plugin:do-thing" in violations[0].message
    assert violations[0].line == 5


# --- marketplace-json-valid ---


def test_marketplace_json_valid_passes(marketplace_repo):
    """Test that valid marketplace.json passes"""
    context = RepositoryContext(marketplace_repo)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_marketplace_owner_must_be_object(temp_dir):
    """Test that owner as a non-object fails"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": "just-a-string",
        "plugins": [],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert any("'owner' must be an object" in v.message for v in violations)


def test_marketplace_owner_must_have_name(temp_dir):
    """Test that owner without name fails"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"email": "test@example.com"},
        "plugins": [],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert any("'owner' must have a 'name' field" in v.message for v in violations)


def test_marketplace_owner_with_name_passes(temp_dir):
    """Test that owner with name passes"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_marketplace_plugin_entry_missing_name(temp_dir):
    """Test that plugin entry without name fails"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {"source": "./plugins/my-plugin", "description": "No name"},
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert any("plugins[0] missing required 'name'" in v.message for v in violations)


def test_marketplace_plugin_entry_missing_source(temp_dir):
    """Test that plugin entry without source fails"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {"name": "my-plugin", "description": "No source"},
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert any("plugins[0] missing required 'source'" in v.message for v in violations)


def test_marketplace_plugin_entry_not_object(temp_dir):
    """Test that non-object plugin entry fails"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": ["not-an-object"],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert any("plugins[0] must be an object" in v.message for v in violations)


def test_marketplace_plugin_entry_valid(temp_dir):
    """Test that valid plugin entries pass"""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [
            {"name": "plugin-one", "source": "./plugins/plugin-one"},
            {
                "name": "plugin-two",
                "source": {"source": "github", "repo": "owner/repo"},
            },
        ],
    }

    with open(claude_dir / "marketplace.json", "w") as f:
        json.dump(marketplace_json, f)

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


# --- severity config validation ---


def test_invalid_severity_string_raises_helpful_error():
    """Test that an invalid severity string gives a helpful ValueError"""
    import pytest

    with pytest.raises(ValueError, match=r"Invalid severity 'critical'.*Valid values:"):
        PluginJsonRequiredRule({"severity": "critical"})


def test_invalid_severity_integer_raises_helpful_error():
    """Test that an integer severity gives a helpful ValueError"""
    import pytest

    with pytest.raises(ValueError, match=r"Invalid severity '42'.*Valid values:"):
        PluginJsonRequiredRule({"severity": 42})


def test_null_severity_uses_default():
    """Test that severity: null falls back to the rule's default severity"""
    rule = PluginJsonRequiredRule({"severity": None})
    assert rule.severity == rule.default_severity()


def test_unhashable_severity_raises_helpful_error():
    """Test that an unhashable severity (list/dict) gives a helpful ValueError"""
    import pytest

    with pytest.raises(ValueError, match=r"Invalid severity.*Valid values:"):
        PluginJsonRequiredRule({"severity": ["error", "warning"]})


def test_valid_severity_override():
    """Test that a valid severity string overrides the default"""
    rule = PluginJsonRequiredRule({"severity": "warning"})
    assert rule.severity == Severity.WARNING


# --- substring false-negative tests ---


def test_skill_frontmatter_substring_does_not_mask_missing_name(temp_dir):
    """Test that 'full-name:' in SKILL.md frontmatter doesn't suppress 'Missing name' violation"""
    import json

    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "test-plugin"}, f)

    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "my-skill"
    skill_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        "---\nfull-name: My Skill\ndescription: A skill\n---\n\n# My Skill\n"
    )

    context = RepositoryContext(plugin_dir)
    rule = SkillFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "name" in violations[0].message.lower()


def test_skill_frontmatter_substring_does_not_mask_missing_description(temp_dir):
    """Test that 'long-description:' in SKILL.md frontmatter doesn't suppress 'Missing description' violation"""
    import json

    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "test-plugin"}, f)

    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    skill_dir = skills_dir / "my-skill"
    skill_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        "---\nname: My Skill\nlong-description: Not real\n---\n\n# My Skill\n"
    )

    context = RepositoryContext(plugin_dir)
    rule = SkillFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "description" in violations[0].message.lower()


def test_command_frontmatter_substring_does_not_mask_missing_description(temp_dir):
    """Test that 'long-description:' in command frontmatter doesn't suppress 'Missing description' violation"""
    import json

    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    with open(claude_dir / "plugin.json", "w") as f:
        json.dump({"name": "test-plugin"}, f)

    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    (commands_dir / "test-cmd.md").write_text(
        "---\nlong-description: Not real\n---\n\n## Name\ntest-plugin:test-cmd\n"
    )

    context = RepositoryContext(plugin_dir)
    rule = CommandFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "description" in violations[0].message.lower()
