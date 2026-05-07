"""
Tests for hook validation rules
"""

import pytest
import json
from pathlib import Path

from skillsaw.rules.builtin.hooks import HooksJsonValidRule
from skillsaw.rule import Severity
from skillsaw.context import RepositoryContext


@pytest.fixture
def plugin_with_valid_hooks(temp_dir):
    """Create a plugin with valid hooks.json"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    # Create plugin.json
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    # Create hooks directory with valid hooks.json
    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    hooks_config = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Write|Edit",
                    "hooks": [
                        {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/format.sh"}
                    ],
                }
            ],
            "PreToolUse": [
                {"matcher": ".*", "hooks": [{"type": "command", "command": "echo 'validating'"}]}
            ],
        }
    }

    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config, indent=2))

    return plugin_dir


@pytest.fixture
def plugin_with_invalid_json(temp_dir):
    """Create a plugin with invalid JSON in hooks.json"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    # Invalid JSON
    (hooks_dir / "hooks.json").write_text('{"hooks": invalid json}')

    return plugin_dir


@pytest.fixture
def plugin_with_missing_hooks_key(temp_dir):
    """Create a plugin with hooks.json missing 'hooks' key"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    hooks_config = {"other_key": "value"}
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    return plugin_dir


@pytest.fixture
def plugin_with_invalid_event_type(temp_dir):
    """Create a plugin with invalid event type"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    hooks_config = {
        "hooks": {
            "InvalidEventType": [
                {"matcher": ".*", "hooks": [{"type": "command", "command": "echo test"}]}
            ]
        }
    }

    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    return plugin_dir


@pytest.fixture
def plugin_with_missing_hook_type(temp_dir):
    """Create a plugin with hook configuration missing 'type' field"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    hooks_config = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "command": "echo test"
                            # Missing "type" field
                        }
                    ],
                }
            ]
        }
    }

    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    return plugin_dir


@pytest.fixture
def plugin_without_hooks(temp_dir):
    """Create a plugin without hooks directory"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    return plugin_dir


def test_valid_hooks_json(plugin_with_valid_hooks):
    """Test that valid hooks.json passes validation"""
    context = RepositoryContext(plugin_with_valid_hooks)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_invalid_json(plugin_with_invalid_json):
    """Test that invalid JSON is detected"""
    context = RepositoryContext(plugin_with_invalid_json)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Invalid JSON" in violations[0].message


def test_missing_hooks_key(plugin_with_missing_hooks_key):
    """Test that missing 'hooks' key is detected"""
    context = RepositoryContext(plugin_with_missing_hooks_key)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'hooks' key" in violations[0].message


def test_invalid_event_type(plugin_with_invalid_event_type):
    """Test that invalid event types are detected"""
    context = RepositoryContext(plugin_with_invalid_event_type)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "Unknown event type" in violations[0].message


def test_missing_hook_type(plugin_with_missing_hook_type):
    """Test that missing 'type' field in hook is detected"""
    context = RepositoryContext(plugin_with_missing_hook_type)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "'type' field" in violations[0].message


def test_no_hooks_directory(plugin_without_hooks):
    """Test that plugins without hooks directory don't trigger violations"""
    context = RepositoryContext(plugin_without_hooks)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_rule_metadata():
    """Test rule metadata"""
    rule = HooksJsonValidRule()
    assert rule.rule_id == "hooks-json-valid"
    assert "hooks" in rule.description.lower()
    assert rule.default_severity().value == "error"


def test_all_valid_event_types(temp_dir):
    """Test that all documented event types are accepted"""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()

    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()

    # Test all valid event types
    valid_events = [
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionRequest",
        "UserPromptSubmit",
        "Notification",
        "Stop",
        "SubagentStart",
        "SubagentStop",
        "SessionStart",
        "SessionEnd",
        "PreCompact",
        "TeammateIdle",
        "TaskCompleted",
        "ConfigChange",
        "WorktreeCreate",
        "WorktreeRemove",
        "InstructionsLoaded",
    ]

    hooks_config = {"hooks": {}}
    for event in valid_events:
        hooks_config["hooks"][event] = [
            {"matcher": ".*", "hooks": [{"type": "command", "command": "echo test"}]}
        ]

    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))

    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def _make_hooks_plugin(temp_dir, hooks_config):
    """Helper to create a plugin with a given hooks config."""
    plugin_dir = temp_dir / "test-plugin"
    plugin_dir.mkdir()
    claude_dir = plugin_dir / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text('{"name": "test-plugin"}')
    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_config))
    return plugin_dir


def test_valid_hook_type_command(temp_dir):
    """Test that valid command hook type passes"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": "echo test"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_hook_type_http(temp_dir):
    """Test that valid http hook type passes"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "http", "url": "https://example.com/hook"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_hook_type_prompt(temp_dir):
    """Test that valid prompt hook type passes"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "prompt", "prompt": "check the output"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_valid_hook_type_agent(temp_dir):
    """Test that valid agent hook type passes"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "agent", "prompt": "review changes"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_invalid_hook_type_value(temp_dir):
    """Test that invalid hook type value is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "invalid_type", "command": "echo test"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "invalid type" in violations[0].message


def test_command_type_missing_command_field(temp_dir):
    """Test that command type without command field is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "requires a 'command' field" in violations[0].message


def test_http_type_missing_url_field(temp_dir):
    """Test that http type without url field is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "http"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "requires a 'url' field" in violations[0].message


def test_prompt_type_missing_prompt_field(temp_dir):
    """Test that prompt type without prompt field is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "prompt"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "requires a 'prompt' field" in violations[0].message


def test_type_specific_field_restriction_warning(temp_dir):
    """Test that using async on http hook produces a warning"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "http",
                                "url": "https://example.com",
                                "async": True,
                            }
                        ],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING
    assert "only valid on types" in violations[0].message


def test_field_type_validation_timeout_string(temp_dir):
    """Test that timeout as string is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo test",
                                "timeout": "5000",
                            }
                        ],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "timeout" in violations[0].message
    assert "int/float" in violations[0].message


def test_field_type_validation_timeout_number(temp_dir):
    """Test that timeout as number passes"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo test",
                                "timeout": 5000,
                            }
                        ],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 0


def test_headers_on_command_type_warning(temp_dir):
    """Test that headers on command type produces a warning"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo test",
                                "headers": {"Authorization": "Bearer token"},
                            }
                        ],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert violations[0].severity == Severity.WARNING
    assert "headers" in violations[0].message


def test_agent_type_missing_prompt_field(temp_dir):
    """Test that agent type without prompt field is detected"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "agent"}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "requires a 'prompt' field" in violations[0].message


def test_required_field_wrong_type(temp_dir):
    """Test that required field with wrong type is detected (e.g. command as int)"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": 123}],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "must be a str" in violations[0].message


def test_timeout_as_boolean_rejected(temp_dir):
    """Test that timeout as boolean is rejected (bool is subclass of int)"""
    plugin_dir = _make_hooks_plugin(
        temp_dir,
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "echo test",
                                "timeout": True,
                            }
                        ],
                    }
                ]
            }
        },
    )
    context = RepositoryContext(plugin_dir)
    rule = HooksJsonValidRule()
    violations = rule.check(context)
    assert len(violations) == 1
    assert "timeout" in violations[0].message
