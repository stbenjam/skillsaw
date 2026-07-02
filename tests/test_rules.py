"""
Tests for builtin rules
"""

import sys
from pathlib import Path


from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.plugins import (
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
)
from skillsaw.rules.builtin.command_format import (
    CommandNamingRule,
    CommandFrontmatterRule,
    CommandNameFormatRule,
    CommandSectionsRule,
)
from skillsaw.rules.builtin.marketplace import (
    MarketplaceJsonValidRule,
    MarketplaceRegistrationRule,
)
from skillsaw.rules.builtin.skills import SkillFrontmatterRule


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


def _marketplace_with(temp_dir, **overrides):
    """Write a minimal marketplace.json with field overrides applied."""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    marketplace_json = {
        "name": "test-marketplace",
        "owner": {"name": "Test Owner"},
        "plugins": [],
    }
    marketplace_json.update(overrides)
    (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))
    return temp_dir


def test_marketplace_duplicate_plugin_names(temp_dir):
    """Duplicate plugin names in the plugins array are an error."""
    repo = _marketplace_with(
        temp_dir,
        plugins=[
            {"name": "my-plugin", "source": "./plugins/my-plugin"},
            {"name": "my-plugin", "source": {"source": "github", "repo": "o/r"}},
        ],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    dupes = [v for v in violations if "duplicate plugin name" in v.message]
    assert len(dupes) == 1
    assert dupes[0].severity == Severity.ERROR
    assert "plugins[1]" in dupes[0].message


def test_marketplace_name_not_kebab_case_warns(temp_dir):
    repo = _marketplace_with(temp_dir, name="My Marketplace")
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    kebab = [v for v in violations if "kebab-case" in v.message]
    assert len(kebab) == 1
    assert kebab[0].severity == Severity.WARNING


def test_marketplace_source_path_traversal_fails(temp_dir):
    repo = _marketplace_with(
        temp_dir,
        plugins=[{"name": "escape", "source": "./../outside"}],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    traversal = [v for v in violations if "'..'" in v.message]
    assert len(traversal) == 1
    assert traversal[0].severity == Severity.ERROR


def test_marketplace_source_missing_dot_slash_info(temp_dir):
    """A relative source without the ./ prefix gets a style nudge, not an error."""
    repo = _marketplace_with(
        temp_dir,
        plugins=[{"name": "my-plugin", "source": "plugins/my-plugin"}],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    style = [v for v in violations if "start with './'" in v.message]
    assert len(style) == 1
    assert style[0].severity == Severity.INFO


def test_marketplace_source_object_required_fields(temp_dir):
    """Each typed source object must carry its required fields."""
    repo = _marketplace_with(
        temp_dir,
        plugins=[
            {"name": "gh", "source": {"source": "github"}},
            {"name": "web", "source": {"source": "url"}},
            {"name": "sub", "source": {"source": "git-subdir", "url": "https://x"}},
            {"name": "pkg", "source": {"source": "npm"}},
        ],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    messages = [v.message for v in violations]
    assert any("plugins[0].source of type 'github' requires a 'repo'" in m for m in messages)
    assert any("plugins[1].source of type 'url' requires a 'url'" in m for m in messages)
    assert any("plugins[2].source of type 'git-subdir' requires a 'path'" in m for m in messages)
    assert any("plugins[3].source of type 'npm' requires a 'package'" in m for m in messages)


def test_marketplace_source_object_valid_types_pass(temp_dir):
    repo = _marketplace_with(
        temp_dir,
        plugins=[
            {"name": "gh", "source": {"source": "github", "repo": "owner/repo"}},
            {"name": "web", "source": {"source": "url", "url": "https://x/p.zip"}},
            {
                "name": "sub",
                "source": {"source": "git-subdir", "url": "https://x", "path": "plugins/sub"},
            },
            {"name": "pkg", "source": {"source": "npm", "package": "@scope/pkg"}},
        ],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    assert len(violations) == 0


def test_marketplace_source_unknown_type_warns(temp_dir):
    """Unknown object source types warn (future types must not hard-fail)."""
    repo = _marketplace_with(
        temp_dir,
        plugins=[{"name": "odd", "source": {"source": "hg", "repo": "o/r"}}],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    unknown = [v for v in violations if "unknown source type 'hg'" in v.message]
    assert len(unknown) == 1
    assert unknown[0].severity == Severity.WARNING


def test_marketplace_source_object_missing_type_fails(temp_dir):
    repo = _marketplace_with(
        temp_dir,
        plugins=[{"name": "odd", "source": {"repo": "o/r"}}],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    assert any("missing required 'source' type field" in v.message for v in violations)


def test_marketplace_source_wrong_type_fails(temp_dir):
    repo = _marketplace_with(
        temp_dir,
        plugins=[{"name": "odd", "source": 42}],
    )
    violations = MarketplaceJsonValidRule().check(RepositoryContext(repo))
    assert any(
        "source must be a relative path string or an object" in v.message for v in violations
    )


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


def test_skill_frontmatter_malformed_yaml_reports_line(temp_dir):
    """Malformed YAML frontmatter should report the error line number."""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(
        '{"name": "test-plugin", "description": "test", "version": "1.0"}'
    )
    skills_dir = plugin_dir / "skills" / "bad-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: bad\ndescription: test\nbad: [unclosed\n---\n# Body\n"
    )
    context = RepositoryContext(plugin_dir)
    rule = SkillFrontmatterRule()
    violations = rule.check(context)
    fm_violations = [v for v in violations if "Invalid frontmatter" in v.message]
    assert len(fm_violations) == 1
    assert fm_violations[0].line is not None
    assert fm_violations[0].line == 5


# --- marketplace-registration autofix ---


def _add_unregistered_plugin(repo, name):
    """Create a plugin directory under repo/plugins that is not registered."""
    import json

    plugin_dir = repo / "plugins" / name
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir(parents=True)
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": "Test plugin",
                "version": "1.0.0",
                "author": {"name": "Test"},
            }
        )
    )
    (plugin_dir / "commands").mkdir()
    return plugin_dir


def _marketplace_with_raw_json(temp_dir, marketplace_text):
    """Marketplace repo with raw marketplace.json text and one unregistered plugin."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text(marketplace_text)
    _add_unregistered_plugin(temp_dir, "plugin-one")
    return temp_dir


def test_marketplace_registration_fix_registers_plugin(marketplace_repo):
    """fix() appends an entry using the plugin's repo-relative path as source,
    preserves existing registrations, and resolves the violation on re-lint."""
    import json

    from skillsaw.rules.builtin.utils import invalidate_read_caches

    _add_unregistered_plugin(marketplace_repo, "plugin-three")
    context = RepositoryContext(marketplace_repo)
    rule = MarketplaceRegistrationRule()

    violations = rule.check(context)
    assert len(violations) == 1

    fixes = rule.fix(context, violations)
    assert len(fixes) == 1
    fix = fixes[0]
    assert fix.violations_fixed == violations

    data = json.loads(fix.fixed_content)
    entries = [p for p in data["plugins"] if p.get("name") == "plugin-three"]
    assert entries == [{"name": "plugin-three", "source": "./plugins/plugin-three"}]
    assert {p["name"] for p in data["plugins"]} == {
        "plugin-one",
        "plugin-two",
        "plugin-three",
    }

    fix.file_path.write_text(fix.fixed_content)
    invalidate_read_caches()
    assert rule.check(RepositoryContext(marketplace_repo)) == []


def test_marketplace_registration_fix_plugins_not_list(temp_dir):
    """Regression: fix() crashed with AttributeError when 'plugins' was a JSON
    object instead of an array. The malformed document is reported by
    marketplace-json-valid; fix() must skip it, not crash."""
    import json

    repo = _marketplace_with_raw_json(
        temp_dir, json.dumps({"name": "m", "owner": {"name": "o"}, "plugins": {}})
    )
    context = RepositoryContext(repo)
    rule = MarketplaceRegistrationRule()

    violations = rule.check(context)
    assert len(violations) == 1
    assert rule.fix(context, violations) == []


def test_marketplace_registration_fix_top_level_array(temp_dir):
    """Regression: fix() crashed with TypeError when marketplace.json held a
    top-level JSON array instead of an object."""
    repo = _marketplace_with_raw_json(temp_dir, "[]")
    context = RepositoryContext(repo)
    rule = MarketplaceRegistrationRule()

    violations = rule.check(context)
    assert len(violations) == 1
    assert rule.fix(context, violations) == []


def test_marketplace_registration_fix_skips_non_dict_entries(temp_dir):
    """Regression: string entries in 'plugins' crashed the duplicate scan with
    AttributeError. They must be skipped while still registering the plugin."""
    import json

    repo = _marketplace_with_raw_json(
        temp_dir,
        json.dumps({"name": "m", "owner": {"name": "o"}, "plugins": ["plugin-zero"]}),
    )
    context = RepositoryContext(repo)
    rule = MarketplaceRegistrationRule()

    violations = rule.check(context)
    assert len(violations) == 1

    fixes = rule.fix(context, violations)
    assert len(fixes) == 1
    data = json.loads(fixes[0].fixed_content)
    assert {"name": "plugin-one", "source": "./plugins/plugin-one"} in data["plugins"]
    assert "plugin-zero" in data["plugins"]


def test_marketplace_registration_fix_invalid_json(temp_dir):
    """Unparseable marketplace.json yields no fixes rather than a crash."""
    repo = _marketplace_with_raw_json(temp_dir, '{"name": broken')
    context = RepositoryContext(repo)
    rule = MarketplaceRegistrationRule()

    violations = rule.check(context)
    assert len(violations) == 1
    assert rule.fix(context, violations) == []


# --- marketplace-json-valid: malformed documents ---


def test_marketplace_json_invalid_json(temp_dir):
    """Unparseable marketplace.json reports a single Invalid JSON error."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text('{"name": broken')

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Invalid JSON" in violations[0].message
    assert violations[0].severity == Severity.ERROR


def test_marketplace_json_top_level_not_object(temp_dir):
    """A top-level JSON array is rejected with a clear message."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text("[]")

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert [v.message for v in violations] == ["Marketplace file must contain a JSON object"]


def test_marketplace_json_missing_required_fields(temp_dir):
    """An empty object reports all three missing required fields."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text("{}")

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert {v.message for v in violations} == {
        "Missing 'name' field",
        "Missing 'owner' field",
        "Missing 'plugins' array",
    }


def test_marketplace_json_plugins_not_array(temp_dir):
    """A non-array 'plugins' value is rejected."""
    import json

    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "marketplace.json").write_text(
        json.dumps({"name": "m", "owner": {"name": "o"}, "plugins": "nope"})
    )

    context = RepositoryContext(temp_dir)
    rule = MarketplaceJsonValidRule()
    violations = rule.check(context)
    assert [v.message for v in violations] == ["'plugins' must be an array"]


# --- command-sections ---


def test_command_sections_all_present(valid_plugin):
    """The valid plugin fixture command has all four recommended sections."""
    context = RepositoryContext(valid_plugin)
    rule = CommandSectionsRule()
    assert rule.check(context) == []


def test_command_sections_missing_all(temp_dir):
    """A command with no section headings reports one warning per section."""
    import json

    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()
    (commands_dir / "deploy.md").write_text("---\ndescription: Deploy\n---\nJust prose.\n")

    context = RepositoryContext(plugin_dir)
    rule = CommandSectionsRule()
    violations = rule.check(context)
    assert {v.message for v in violations} == {
        "Missing recommended section '## Name'",
        "Missing recommended section '## Synopsis'",
        "Missing recommended section '## Description'",
        "Missing recommended section '## Implementation'",
    }
    assert all(v.severity == Severity.WARNING for v in violations)


def test_command_sections_partial(temp_dir):
    """Only the absent sections are reported."""
    import json

    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(json.dumps({"name": "test-plugin"}))
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()
    (commands_dir / "deploy.md").write_text(
        "---\ndescription: Deploy\n---\n"
        "## Name\ndeploy\n\n## Synopsis\n/deploy\n\n## Description\nDeploys.\n"
    )

    context = RepositoryContext(plugin_dir)
    rule = CommandSectionsRule()
    violations = rule.check(context)
    assert [v.message for v in violations] == ["Missing recommended section '## Implementation'"]
