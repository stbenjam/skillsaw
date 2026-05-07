"""
Tests for MCP (Model Context Protocol) validation rules
"""

import pytest
import json
from pathlib import Path

from skillsaw.rules.builtin.mcp import McpValidJsonRule, McpProhibitedRule
from skillsaw.context import RepositoryContext


def _create_plugin_with_mcp(temp_dir, mcp_config):
    """Helper to create a plugin with a given MCP config."""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')
    (plugin_dir / ".mcp.json").write_text(json.dumps(mcp_config))
    return plugin_dir


@pytest.fixture
def plugin_with_valid_mcp_json(temp_dir):
    """Create a plugin with valid .mcp.json"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    # Create plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-plugin",
                "description": "Test plugin",
                "version": "1.0.0",
                "author": {"name": "Test"},
            }
        )
    )

    # Create valid .mcp.json
    mcp_config = {
        "mcpServers": {
            "database-server": {
                "command": "${CLAUDE_PLUGIN_ROOT}/servers/db-server",
                "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"],
                "env": {"DB_HOST": "localhost"},
                "cwd": "/tmp",
            },
            "simple-server": {"command": "node", "args": ["server.js"]},
        }
    }

    (plugin_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2))

    return plugin_dir


@pytest.fixture
def plugin_with_mcp_in_plugin_json(temp_dir):
    """Create a plugin with mcpServers in plugin.json"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()

    plugin_data = {
        "name": "test-plugin",
        "description": "Test plugin",
        "version": "1.0.0",
        "author": {"name": "Test"},
        "mcpServers": {"test-server": {"command": "python", "args": ["-m", "server"]}},
    }

    (claude_dir / "plugin.json").write_text(json.dumps(plugin_data, indent=2))

    return plugin_dir


@pytest.fixture
def plugin_with_invalid_mcp_json(temp_dir):
    """Create a plugin with invalid JSON in .mcp.json"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    # Invalid JSON - can't use helper since this needs invalid JSON
    (plugin_dir / ".mcp.json").write_text('{"mcpServers": invalid}')

    return plugin_dir


@pytest.fixture
def plugin_with_missing_mcp_servers_key(temp_dir):
    """Create a plugin with .mcp.json missing mcpServers key"""
    mcp_config = {"other_key": "value"}
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_missing_command_field(temp_dir):
    """Create a plugin with MCP server missing command field"""
    mcp_config = {
        "mcpServers": {
            "test-server": {
                "args": ["test"]
                # Missing "command" field
            }
        }
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_invalid_args_type(temp_dir):
    """Create a plugin with MCP server having invalid args type"""
    mcp_config = {
        "mcpServers": {"test-server": {"command": "node", "args": "invalid-should-be-array"}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_invalid_env_type(temp_dir):
    """Create a plugin with MCP server having invalid env type"""
    mcp_config = {
        "mcpServers": {"test-server": {"command": "node", "env": ["invalid-should-be-object"]}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_without_mcp(temp_dir):
    """Create a plugin without any MCP configuration"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-plugin",
                "description": "Test plugin",
                "version": "1.0.0",
                "author": {"name": "Test"},
            }
        )
    )

    # Create a command to make it a valid plugin
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    return plugin_dir


@pytest.fixture
def plugin_with_http_mcp(temp_dir):
    """Create a plugin with valid HTTP MCP configuration"""
    mcp_config = {
        "mcpServers": {"http-server": {"type": "http", "url": "https://api.example.com/mcp"}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_sse_mcp(temp_dir):
    """Create a plugin with valid SSE MCP configuration"""
    mcp_config = {
        "mcpServers": {"sse-server": {"type": "sse", "url": "https://events.example.com/mcp"}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_explicit_stdio_mcp(temp_dir):
    """Create a plugin with explicit stdio type MCP configuration"""
    mcp_config = {
        "mcpServers": {"stdio-server": {"type": "stdio", "command": "node", "args": ["server.js"]}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_http_mcp_missing_url(temp_dir):
    """Create a plugin with HTTP MCP missing url field"""
    mcp_config = {
        "mcpServers": {
            "http-server": {
                "type": "http"
                # Missing "url" field
            }
        }
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_sse_mcp_missing_url(temp_dir):
    """Create a plugin with SSE MCP missing url field"""
    mcp_config = {
        "mcpServers": {
            "sse-server": {
                "type": "sse"
                # Missing "url" field
            }
        }
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_invalid_type(temp_dir):
    """Create a plugin with invalid MCP type"""
    mcp_config = {
        "mcpServers": {
            "invalid-server": {"type": "websocket", "url": "wss://example.com"}  # Invalid type
        }
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


@pytest.fixture
def plugin_with_invalid_url_type(temp_dir):
    """Create a plugin with HTTP MCP having invalid url type"""
    mcp_config = {
        "mcpServers": {"http-server": {"type": "http", "url": ["invalid-should-be-string"]}}
    }
    return _create_plugin_with_mcp(temp_dir, mcp_config)


# Tests for McpValidJsonRule


def test_valid_mcp_json(plugin_with_valid_mcp_json):
    """Test that valid .mcp.json passes validation"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_mcp_in_plugin_json(plugin_with_mcp_in_plugin_json):
    """Test that valid mcpServers in plugin.json passes validation"""
    context = RepositoryContext(plugin_with_mcp_in_plugin_json)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_invalid_mcp_json(plugin_with_invalid_mcp_json):
    """Test that invalid JSON in .mcp.json is detected"""
    context = RepositoryContext(plugin_with_invalid_mcp_json)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Invalid JSON" in violations[0].message


def test_missing_mcp_servers_key(plugin_with_missing_mcp_servers_key):
    """Test that missing mcpServers key is detected"""
    context = RepositoryContext(plugin_with_missing_mcp_servers_key)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "mcpServers" in violations[0].message


def test_missing_command_field(plugin_with_missing_command_field):
    """Test that missing command field is detected"""
    context = RepositoryContext(plugin_with_missing_command_field)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'command' field" in violations[0].message


def test_invalid_args_type(plugin_with_invalid_args_type):
    """Test that invalid args type is detected"""
    context = RepositoryContext(plugin_with_invalid_args_type)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'args' must be an array" in violations[0].message


def test_invalid_env_type(plugin_with_invalid_env_type):
    """Test that invalid env type is detected"""
    context = RepositoryContext(plugin_with_invalid_env_type)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'env' must be an object" in violations[0].message


def test_no_mcp_configuration(plugin_without_mcp):
    """Test that plugins without MCP configuration don't trigger violations"""
    context = RepositoryContext(plugin_without_mcp)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_mcp_valid_json_rule_metadata():
    """Test rule metadata"""
    rule = McpValidJsonRule()
    assert rule.rule_id == "mcp-valid-json"
    assert "MCP" in rule.description
    assert rule.default_severity().value == "error"


def test_http_mcp_valid(plugin_with_http_mcp):
    """Test that valid HTTP MCP passes validation"""
    context = RepositoryContext(plugin_with_http_mcp)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_sse_mcp_valid(plugin_with_sse_mcp):
    """Test that valid SSE MCP passes validation"""
    context = RepositoryContext(plugin_with_sse_mcp)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_explicit_stdio_mcp_valid(plugin_with_explicit_stdio_mcp):
    """Test that explicit stdio type MCP passes validation"""
    context = RepositoryContext(plugin_with_explicit_stdio_mcp)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_http_mcp_missing_url(plugin_with_http_mcp_missing_url):
    """Test that HTTP MCP missing url field is detected"""
    context = RepositoryContext(plugin_with_http_mcp_missing_url)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'url' field" in violations[0].message
    assert "http" in violations[0].message


def test_sse_mcp_missing_url(plugin_with_sse_mcp_missing_url):
    """Test that SSE MCP missing url field is detected"""
    context = RepositoryContext(plugin_with_sse_mcp_missing_url)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'url' field" in violations[0].message
    assert "sse" in violations[0].message


def test_invalid_type(plugin_with_invalid_type):
    """Test that invalid type value is detected"""
    context = RepositoryContext(plugin_with_invalid_type)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "invalid type" in violations[0].message
    assert "websocket" in violations[0].message


def test_invalid_url_type(plugin_with_invalid_url_type):
    """Test that invalid url type is detected"""
    context = RepositoryContext(plugin_with_invalid_url_type)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'url' must be a string" in violations[0].message


# Tests for McpProhibitedRule


def test_mcp_prohibited_detects_mcp_json(plugin_with_valid_mcp_json):
    """Test that mcp-prohibited detects .mcp.json"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert ".mcp.json" in violations[0].message


def test_mcp_prohibited_detects_plugin_json(plugin_with_mcp_in_plugin_json):
    """Test that mcp-prohibited detects mcpServers in plugin.json"""
    context = RepositoryContext(plugin_with_mcp_in_plugin_json)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "plugin.json" in violations[0].message


def test_mcp_prohibited_allows_no_mcp(plugin_without_mcp):
    """Test that mcp-prohibited passes when no MCP is configured"""
    context = RepositoryContext(plugin_without_mcp)
    rule = McpProhibitedRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_mcp_prohibited_rule_metadata():
    """Test rule metadata"""
    rule = McpProhibitedRule()
    assert rule.rule_id == "mcp-prohibited"
    assert "MCP" in rule.description
    assert rule.default_severity().value == "error"


def test_both_mcp_json_and_plugin_json(temp_dir):
    """Test plugin with both .mcp.json and mcpServers in plugin.json"""
    # Create .mcp.json
    mcp_config = {
        "mcpServers": {"standalone-server": {"command": "python", "args": ["-m", "server"]}}
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)

    # Override plugin.json to add mcpServers
    claude_dir = plugin_dir / ".claude-plugin"
    plugin_data = {
        "name": "test-plugin",
        "description": "Test",
        "version": "1.0.0",
        "author": {"name": "Test"},
        "mcpServers": {"inline-server": {"command": "node", "args": ["server.js"]}},
    }
    (claude_dir / "plugin.json").write_text(json.dumps(plugin_data))

    context = RepositoryContext(plugin_dir)

    # Both should be valid
    valid_rule = McpValidJsonRule()
    violations = valid_rule.check(context)
    assert len(violations) == 0

    # Both should be detected by prohibited rule
    prohibited_rule = McpProhibitedRule()
    violations = prohibited_rule.check(context)
    assert len(violations) == 2


def test_invalid_cwd_type(temp_dir):
    """Test that invalid cwd type is detected"""
    mcp_config = {
        "mcpServers": {"test-server": {"command": "node", "cwd": ["invalid-should-be-string"]}}
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)

    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'cwd' must be a string" in violations[0].message


def test_mcp_servers_not_object(temp_dir):
    """Test that mcpServers must be an object"""
    mcp_config = {"mcpServers": ["invalid-should-be-object"]}
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)

    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'mcpServers' must be a JSON object" in violations[0].message


# Tests for McpProhibitedRule allowlist


def test_mcp_prohibited_no_allowlist(plugin_with_valid_mcp_json):
    """Test that without allowlist, all MCP servers are prohibited"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    rule = McpProhibitedRule(config={})
    violations = rule.check(context)
    assert len(violations) == 1
    assert ".mcp.json" in violations[0].message


def test_mcp_prohibited_with_allowlist_all_allowed(plugin_with_valid_mcp_json):
    """Test that servers in allowlist are allowed"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    # Allowlist both servers from the fixture
    rule = McpProhibitedRule(config={"allowlist": ["database-server", "simple-server"]})
    violations = rule.check(context)
    assert len(violations) == 0


def test_mcp_prohibited_with_allowlist_partial(plugin_with_valid_mcp_json):
    """Test that only non-allowlisted servers trigger violations"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    # Only allow one server, the other should be flagged
    rule = McpProhibitedRule(config={"allowlist": ["database-server"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "non-allowlisted" in violations[0].message
    assert "simple-server" in violations[0].message
    assert "database-server" not in violations[0].message


def test_mcp_prohibited_with_allowlist_none_allowed(plugin_with_valid_mcp_json):
    """Test that servers not in allowlist are prohibited"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    rule = McpProhibitedRule(config={"allowlist": ["some-other-server"]})
    violations = rule.check(context)
    assert len(violations) == 1
    assert "non-allowlisted" in violations[0].message
    # Both servers should be mentioned (sorted alphabetically)
    assert "database-server" in violations[0].message
    assert "simple-server" in violations[0].message


def test_mcp_prohibited_with_allowlist_plugin_json(plugin_with_mcp_in_plugin_json):
    """Test allowlist works with mcpServers in plugin.json"""
    context = RepositoryContext(plugin_with_mcp_in_plugin_json)
    # Allow the test-server from the fixture
    rule = McpProhibitedRule(config={"allowlist": ["test-server"]})
    violations = rule.check(context)
    assert len(violations) == 0


def test_mcp_prohibited_with_empty_allowlist(plugin_with_valid_mcp_json):
    """Test that empty allowlist prohibits all servers"""
    context = RepositoryContext(plugin_with_valid_mcp_json)
    rule = McpProhibitedRule(config={"allowlist": []})
    violations = rule.check(context)
    assert len(violations) == 1
    assert ".mcp.json" in violations[0].message


def test_valid_headers_on_http_server(temp_dir):
    """Test that valid headers field on HTTP MCP server passes"""
    mcp_config = {
        "mcpServers": {
            "http-server": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer token"},
            }
        }
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_invalid_headers_type(temp_dir):
    """Test that invalid headers type is detected"""
    mcp_config = {
        "mcpServers": {
            "http-server": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": "invalid-should-be-object",
            }
        }
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'headers' must be an object" in violations[0].message


def test_valid_startup_timeout(temp_dir):
    """Test that valid startupTimeout field passes"""
    mcp_config = {
        "mcpServers": {
            "test-server": {
                "command": "node",
                "args": ["server.js"],
                "startupTimeout": 30000,
            }
        }
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_invalid_startup_timeout_type(temp_dir):
    """Test that invalid startupTimeout type is detected"""
    mcp_config = {
        "mcpServers": {
            "test-server": {
                "command": "node",
                "args": ["server.js"],
                "startupTimeout": "slow",
            }
        }
    }
    plugin_dir = _create_plugin_with_mcp(temp_dir, mcp_config)
    context = RepositoryContext(plugin_dir)
    rule = McpValidJsonRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'startupTimeout' must be a number" in violations[0].message
