"""
Tests for agent validation rules
"""

import pytest
from pathlib import Path

from skillsaw.rules.builtin.agents import AgentFrontmatterRule
from skillsaw.context import RepositoryContext


@pytest.fixture
def plugin_with_valid_agent(temp_dir):
    """Create a plugin with a valid agent file"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    # Create plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    # Create agents directory with valid agent
    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """---
name: test-agent
description: "An agent that helps with testing"
---

# Test Agent

This is a test agent.
"""
    (agents_dir / "test-agent.md").write_text(agent_content)

    return plugin_dir


@pytest.fixture
def plugin_with_missing_frontmatter(temp_dir):
    """Create a plugin with agent missing frontmatter"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """# Test Agent

This agent has no frontmatter.
"""
    (agents_dir / "no-frontmatter.md").write_text(agent_content)

    return plugin_dir


@pytest.fixture
def plugin_with_invalid_frontmatter(temp_dir):
    """Create a plugin with agent with invalid frontmatter"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """---
This is not valid YAML frontmatter
---

# Test Agent
"""
    (agents_dir / "invalid.md").write_text(agent_content)

    return plugin_dir


@pytest.fixture
def plugin_with_missing_description(temp_dir):
    """Create a plugin with agent missing description"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """---
name: test-agent
---

# Test Agent
"""
    (agents_dir / "no-description.md").write_text(agent_content)

    return plugin_dir


@pytest.fixture
def plugin_with_missing_name(temp_dir):
    """Create a plugin with agent missing name"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """---
description: "Test agent"
---

# Test Agent
"""
    (agents_dir / "no-name.md").write_text(agent_content)

    return plugin_dir


@pytest.fixture
def plugin_without_agents(temp_dir):
    """Create a plugin without agents directory"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    # Create commands directory instead
    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir()

    return plugin_dir


def test_valid_agent_frontmatter(plugin_with_valid_agent):
    """Test that valid agent frontmatter passes"""
    context = RepositoryContext(plugin_with_valid_agent)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_missing_frontmatter(plugin_with_missing_frontmatter):
    """Test that missing frontmatter is detected"""
    context = RepositoryContext(plugin_with_missing_frontmatter)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Missing frontmatter" in violations[0].message


def test_invalid_frontmatter_format(plugin_with_invalid_frontmatter):
    """Test that invalid frontmatter format is detected"""
    context = RepositoryContext(plugin_with_invalid_frontmatter)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    # Should detect invalid format
    assert len(violations) >= 1


def test_missing_description(plugin_with_missing_description):
    """Test that missing description is detected"""
    context = RepositoryContext(plugin_with_missing_description)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "description" in violations[0].message.lower()


def test_missing_name(plugin_with_missing_name):
    """Test that missing name is detected"""
    context = RepositoryContext(plugin_with_missing_name)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "name" in violations[0].message.lower()


def test_no_agents_directory(plugin_without_agents):
    """Test that plugins without agents directory don't trigger violations"""
    context = RepositoryContext(plugin_without_agents)
    rule = AgentFrontmatterRule()
    violations = rule.check(context)
    assert len(violations) == 0


@pytest.fixture
def plugin_with_missing_both_fields(temp_dir):
    """Create a plugin with agent missing both name and description"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir()

    agent_content = """---
some-other-field: value
---

# Test Agent
"""
    (agents_dir / "both-missing.md").write_text(agent_content)

    return plugin_dir


def test_fix_both_name_and_description_missing(plugin_with_missing_both_fields):
    """Test that fixing both missing name and description produces a single
    AutofixResult that contains both fields, not two conflicting results."""
    context = RepositoryContext(plugin_with_missing_both_fields)
    rule = AgentFrontmatterRule()

    violations = rule.check(context)
    assert len(violations) == 2
    messages = {v.message for v in violations}
    assert "Missing 'name' in frontmatter" in messages
    assert "Missing 'description' in frontmatter" in messages

    fixes = rule.fix(context, violations)
    # Must produce exactly one fix for the file, not two conflicting ones
    assert len(fixes) == 1

    fix = fixes[0]
    assert "name: both-missing" in fix.fixed_content
    assert "description: " in fix.fixed_content
    # Both violations should be covered by the single fix
    assert len(fix.violations_fixed) == 2


def test_rule_metadata():
    """Test rule metadata"""
    rule = AgentFrontmatterRule()
    assert rule.rule_id == "agent-frontmatter"
    assert "agent" in rule.description.lower()
    assert rule.default_severity().value == "error"
