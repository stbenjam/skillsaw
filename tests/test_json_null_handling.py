"""
Tests for handling JSON null and non-dict values in plugin files.

Covers crash paths where read_json() returns (None, None) for valid JSON
containing just ``null``, and where marketplace plugins list contains
non-dict entries (e.g. bare strings).
"""

import json
from pathlib import Path

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.plugin_structure import PluginJsonValidRule
from skillsaw.rules.builtin.mcp import McpValidJsonRule, McpProhibitedRule

# -- helpers -----------------------------------------------------------------


def _create_single_plugin(temp_dir, plugin_json_content: str) -> Path:
    """Create a minimal single-plugin repo with arbitrary plugin.json content."""
    plugin_dir = temp_dir / "null-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(plugin_json_content)
    return plugin_dir


def _create_plugin_with_mcp_content(temp_dir, mcp_content: str) -> Path:
    """Create a plugin with a valid plugin.json and arbitrary .mcp.json content."""
    plugin_dir = temp_dir / "mcp-null-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "mcp-null-plugin"}')
    (plugin_dir / ".mcp.json").write_text(mcp_content)
    return plugin_dir


# -- plugin_structure.py: PluginJsonValidRule --------------------------------


def test_plugin_json_null_does_not_crash(temp_dir):
    """plugin.json containing JSON null must not raise TypeError."""
    plugin_dir = _create_single_plugin(temp_dir, "null")
    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Expected JSON object" in violations[0].message


def test_plugin_json_array_does_not_crash(temp_dir):
    """plugin.json containing a JSON array must not raise TypeError."""
    plugin_dir = _create_single_plugin(temp_dir, "[1, 2, 3]")
    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Expected JSON object" in violations[0].message


def test_plugin_json_string_does_not_crash(temp_dir):
    """plugin.json containing a JSON string must not raise TypeError."""
    plugin_dir = _create_single_plugin(temp_dir, '"just a string"')
    context = RepositoryContext(plugin_dir)
    rule = PluginJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Expected JSON object" in violations[0].message


# -- mcp.py: McpValidJsonRule ._validate_mcp_file ---------------------------


def test_mcp_json_null_does_not_crash(temp_dir):
    """.mcp.json containing JSON null must not raise TypeError."""
    plugin_dir = _create_plugin_with_mcp_content(temp_dir, "null")
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    msgs = [v.message for v in violations]
    assert any("JSON object" in m for m in msgs)


def test_mcp_json_array_does_not_crash(temp_dir):
    """.mcp.json containing a JSON array must not raise TypeError."""
    plugin_dir = _create_plugin_with_mcp_content(temp_dir, "[]")
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    msgs = [v.message for v in violations]
    assert any("JSON object" in m for m in msgs)


# -- mcp.py: McpValidJsonRule ._validate_plugin_json_mcp --------------------


def test_plugin_json_null_mcp_valid_rule(temp_dir):
    """McpValidJsonRule must not crash when plugin.json is JSON null."""
    plugin_dir = _create_single_plugin(temp_dir, "null")
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    # Should not raise
    violations = rule.check(context)
    # No MCP-specific violations expected; the non-dict is silently skipped
    # (plugin-json-valid rule handles that case)
    assert isinstance(violations, list)


def test_plugin_json_null_mcp_servers_mcp_valid_rule(temp_dir):
    """McpValidJsonRule must not crash when plugin.json has mcpServers: null."""
    plugin_dir = _create_single_plugin(
        temp_dir, json.dumps({"name": "null-mcp-valid", "mcpServers": None})
    )
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    msgs = [v.message for v in violations]
    assert any("JSON object" in m for m in msgs)


def test_plugin_json_list_mcp_servers_mcp_valid_rule(temp_dir):
    """McpValidJsonRule must not crash when plugin.json has mcpServers: []."""
    plugin_dir = _create_single_plugin(
        temp_dir, json.dumps({"name": "list-mcp-valid", "mcpServers": []})
    )
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    msgs = [v.message for v in violations]
    assert any("JSON object" in m for m in msgs)


# -- mcp.py: McpProhibitedRule ._check_mcp_file & ._check_plugin_json -------


def test_mcp_prohibited_null_mcp_json(temp_dir):
    """McpProhibitedRule must not crash when .mcp.json is JSON null."""
    plugin_dir = _create_plugin_with_mcp_content(temp_dir, "null")
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    # null has no mcpServers, so nothing prohibited
    assert len(violations) == 0


def test_mcp_prohibited_null_plugin_json(temp_dir):
    """McpProhibitedRule must not crash when plugin.json is JSON null."""
    plugin_dir = _create_single_plugin(temp_dir, "null")
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert isinstance(violations, list)


def test_mcp_prohibited_null_mcp_servers(temp_dir):
    """McpProhibitedRule must not crash when mcpServers is null in .mcp.json."""
    plugin_dir = _create_plugin_with_mcp_content(temp_dir, json.dumps({"mcpServers": None}))
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    assert len(violations) == 0


def test_mcp_prohibited_list_mcp_servers(temp_dir):
    """McpProhibitedRule must not crash when mcpServers is a list in .mcp.json."""
    plugin_dir = _create_plugin_with_mcp_content(
        temp_dir, json.dumps({"mcpServers": ["server-a", "server-b"]})
    )
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    assert len(violations) == 0


def test_mcp_prohibited_null_mcp_servers_in_plugin_json(temp_dir):
    """McpProhibitedRule must not crash when plugin.json has mcpServers: null."""
    plugin_dir = _create_single_plugin(
        temp_dir, json.dumps({"name": "null-mcp", "mcpServers": None})
    )
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    assert len(violations) == 0


def test_mcp_prohibited_list_mcp_servers_in_plugin_json(temp_dir):
    """McpProhibitedRule must not crash when plugin.json has mcpServers: []."""
    plugin_dir = _create_single_plugin(temp_dir, json.dumps({"name": "list-mcp", "mcpServers": []}))
    context = RepositoryContext(plugin_dir)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert isinstance(violations, list)
    assert len(violations) == 0


# -- context.py: is_registered_in_marketplace --------------------------------


def test_marketplace_with_null_plugins(temp_dir):
    """is_registered_in_marketplace must not crash when plugins is null."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    marketplace_json = {
        "name": "null-plugins-marketplace",
        "owner": {"name": "Owner"},
        "plugins": None,
    }
    (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))

    context = RepositoryContext(temp_dir)
    assert not context.is_registered_in_marketplace("any-plugin")


def test_marketplace_with_string_plugin_entries(temp_dir):
    """is_registered_in_marketplace must not crash on non-dict plugin entries."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    # marketplace.json with string entries instead of dicts
    marketplace_json = {
        "name": "bad-marketplace",
        "owner": {"name": "Owner"},
        "plugins": ["plugin-a", "plugin-b"],
    }
    (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))

    context = RepositoryContext(temp_dir)
    # Must not raise AttributeError
    assert not context.is_registered_in_marketplace("plugin-a")
    assert not context.is_registered_in_marketplace("nonexistent")


def test_marketplace_with_mixed_plugin_entries(temp_dir):
    """is_registered_in_marketplace handles a mix of dicts and non-dicts."""
    claude_dir = temp_dir / ".claude-plugin"
    claude_dir.mkdir()

    plugins_dir = temp_dir / "plugins"
    plugins_dir.mkdir()

    marketplace_json = {
        "name": "mixed-marketplace",
        "owner": {"name": "Owner"},
        "plugins": [
            "bare-string",
            {"name": "real-plugin", "source": "./plugins/real-plugin", "description": "A plugin"},
            42,
            None,
        ],
    }
    (claude_dir / "marketplace.json").write_text(json.dumps(marketplace_json))

    # Create the real-plugin directory so discovery doesn't skip it
    real_plugin = plugins_dir / "real-plugin"
    real_plugin.mkdir()
    real_claude = real_plugin / ".claude-plugin"
    real_claude.mkdir()
    (real_claude / "plugin.json").write_text('{"name": "real-plugin"}')

    context = RepositoryContext(temp_dir)
    assert context.is_registered_in_marketplace("real-plugin")
    assert not context.is_registered_in_marketplace("bare-string")
    assert not context.is_registered_in_marketplace("nonexistent")
