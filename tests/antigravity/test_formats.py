"""Format and schema validation tests for Antigravity primitives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.formats.antigravity import (
    NON_TOOL_HOOK_EVENTS,
    TOOL_HOOK_EVENTS,
    validate_antigravity_config,
    validate_antigravity_hooks,
    validate_antigravity_manifest,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "antigravity"


# ==============================================================================
# validate_antigravity_manifest
# ==============================================================================


class TestValidateAntigravityManifest:
    """Tests for ``validate_antigravity_manifest``."""

    def test_valid_minimal_manifest(self) -> None:
        assert validate_antigravity_manifest({"name": "my-plugin"}) == []

    def test_valid_full_manifest(self) -> None:
        manifest = {
            "name": "my-plugin",
            "description": "A comprehensive test plugin",
            "version": "1.2.3",
            "author": {"name": "Antigravity Team"},
            "disabled": False,
        }
        assert validate_antigravity_manifest(manifest) == []

    def test_valid_string_author(self) -> None:
        manifest = {
            "name": "my-plugin",
            "author": "Antigravity Author",
        }
        assert validate_antigravity_manifest(manifest) == []

    def test_valid_author_dict_without_name(self) -> None:
        manifest = {
            "name": "my-plugin",
            "author": {"email": "dev@example.com"},
        }
        assert validate_antigravity_manifest(manifest) == []

    def test_valid_disabled_flag(self) -> None:
        assert validate_antigravity_manifest({"name": "plugin", "disabled": True}) == []

    def test_valid_fixture_manifest(self) -> None:
        fixture_path = (
            FIXTURES_DIR / "valid-plugin" / ".agents" / "plugins" / "valid-plugin" / "plugin.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert validate_antigravity_manifest(data) == []

    @pytest.mark.parametrize("invalid_root", [None, 42, "string", [1, 2, 3], True])
    def test_non_dict_root_rejected(self, invalid_root) -> None:
        errors = validate_antigravity_manifest(invalid_root)
        assert errors == ["manifest root must be a JSON object"]

    def test_unknown_fields_reported(self) -> None:
        manifest = {
            "name": "my-plugin",
            "extra_field": 123,
            "another_field": "bad",
        }
        errors = validate_antigravity_manifest(manifest)
        assert "unknown field 'another_field'" in errors
        assert "unknown field 'extra_field'" in errors

    @pytest.mark.parametrize(
        "invalid_name",
        ["", "   ", 123, [], {}, None],
    )
    def test_invalid_name_type_or_empty(self, invalid_name) -> None:
        errors = validate_antigravity_manifest({"name": invalid_name})
        assert "'name' must be a non-empty string" in errors

    @pytest.mark.parametrize(
        "bad_format_name",
        [
            ".starts-with-dot",
            "has.dot",
            "Invalid Name!",
            "has space",
            "foo@bar",
        ],
    )
    def test_invalid_name_regex(self, bad_format_name) -> None:
        errors = validate_antigravity_manifest({"name": bad_format_name})
        assert any("invalid plugin name" in err for err in errors)

    @pytest.mark.parametrize(
        "valid_name",
        ["a", "my-plugin", "plugin_v2", "-starts-with-dash", "_starts-with-underscore"],
    )
    def test_valid_name_regex(self, valid_name) -> None:
        assert validate_antigravity_manifest({"name": valid_name}) == []

    @pytest.mark.parametrize("bad_desc", [123, True, [], {}])
    def test_invalid_description_type(self, bad_desc) -> None:
        errors = validate_antigravity_manifest({"name": "p", "description": bad_desc})
        assert "'description' must be a string" in errors

    @pytest.mark.parametrize("bad_version", ["", "   ", 123, None, []])
    def test_invalid_version_type_or_empty(self, bad_version) -> None:
        errors = validate_antigravity_manifest({"name": "p", "version": bad_version})
        assert "'version' must be a non-empty string" in errors

    @pytest.mark.parametrize("bad_disabled", ["yes", "no", 1, 0, [], {}])
    def test_invalid_disabled_type(self, bad_disabled) -> None:
        errors = validate_antigravity_manifest({"name": "p", "disabled": bad_disabled})
        assert "'disabled' must be a boolean" in errors

    @pytest.mark.parametrize("bad_author", [123, False, [1, 2]])
    def test_invalid_author_type(self, bad_author) -> None:
        errors = validate_antigravity_manifest({"name": "p", "author": bad_author})
        assert "'author' must be an object or a string" in errors

    def test_invalid_author_name_type(self) -> None:
        errors = validate_antigravity_manifest({"name": "p", "author": {"name": 123}})
        assert "'author.name' must be a string" in errors

    def test_invalid_fixture_manifest(self) -> None:
        fixture_path = (
            FIXTURES_DIR
            / "invalid-plugin"
            / ".agents"
            / "plugins"
            / "invalid-plugin"
            / "plugin.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        errors = validate_antigravity_manifest(data)
        assert "unknown field 'extra_unknown'" in errors
        assert any("invalid plugin name 'Invalid Name!'" in e for e in errors)
        assert "'version' must be a non-empty string" in errors
        assert "'disabled' must be a boolean" in errors


# ==============================================================================
# validate_antigravity_hooks
# ==============================================================================


class TestValidateAntigravityHooks:
    """Tests for ``validate_antigravity_hooks``."""

    def test_valid_fixture_hooks(self) -> None:
        fixture_path = (
            FIXTURES_DIR / "valid-plugin" / ".agents" / "plugins" / "valid-plugin" / "hooks.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert validate_antigravity_hooks(data) == []

    def test_valid_tool_hook_events(self) -> None:
        for event in TOOL_HOOK_EVENTS:
            data = {
                "hook-1": {
                    "enabled": True,
                    event: [
                        {
                            "matcher": "^(run_command|view_file)$",
                            "hooks": [
                                {
                                    "command": "echo check",
                                    "type": "command",
                                    "timeout": 15,
                                }
                            ],
                        }
                    ],
                }
            }
            assert validate_antigravity_hooks(data) == []

    def test_valid_tool_hook_without_matcher(self) -> None:
        """Matcher is optional in tool hook entries."""
        data = {"my-hook": {"PreToolUse": [{"hooks": [{"command": "echo run"}]}]}}
        assert validate_antigravity_hooks(data) == []

    def test_valid_non_tool_hook_events(self) -> None:
        for event in NON_TOOL_HOOK_EVENTS:
            data = {
                "lifecycle-hook": {
                    "enabled": False,
                    event: [
                        {
                            "command": "echo lifecycle",
                            "timeout": 5.5,
                        }
                    ],
                }
            }
            assert validate_antigravity_hooks(data) == []

    def test_valid_extra_events(self) -> None:
        data = {"custom-hook": {"CustomEvent": [{"command": "echo custom"}]}}
        assert validate_antigravity_hooks(data, extra_events={"CustomEvent"}) == []

    @pytest.mark.parametrize("invalid_root", [None, 123, "hooks", [], False])
    def test_non_dict_root_rejected(self, invalid_root) -> None:
        assert validate_antigravity_hooks(invalid_root) == ["hooks root must be a JSON object"]

    def test_non_dict_hook_spec_rejected(self) -> None:
        errors = validate_antigravity_hooks({"bad-hook": "not-a-dict"})
        assert errors == ["hook 'bad-hook': hook configuration must be a JSON object"]

    @pytest.mark.parametrize("bad_enabled", ["true", 1, 0, [], {}])
    def test_invalid_enabled_type(self, bad_enabled) -> None:
        errors = validate_antigravity_hooks({"hook": {"enabled": bad_enabled}})
        assert "hook 'hook': 'enabled' must be a boolean" in errors

    def test_unknown_event_rejected(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"UnknownEvent": []}})
        assert "hook 'hook': unknown event 'UnknownEvent'" in errors

    def test_non_list_event_value(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreInvocation": {}}})
        assert "hook 'hook': event 'PreInvocation' must be a list" in errors

    def test_tool_event_matcher_entry_not_dict(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreToolUse": ["not-a-dict"]}})
        assert "hook 'hook': PreToolUse[0]: matcher entry must be an object" in errors

    def test_tool_event_matcher_not_string(self) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreToolUse": [{"matcher": 123, "hooks": [{"command": "echo"}]}]}}
        )
        assert "hook 'hook': PreToolUse[0]: 'matcher' must be a string" in errors

    def test_tool_event_matcher_invalid_regex(self) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreToolUse": [{"matcher": "[unterminated", "hooks": [{"command": "echo"}]}]}}
        )
        assert any("invalid regex in 'matcher'" in err for err in errors)

    def test_tool_event_missing_hooks_field(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreToolUse": [{"matcher": "run_command"}]}})
        assert "hook 'hook': PreToolUse[0]: missing required field 'hooks'" in errors

    def test_tool_event_hooks_not_list(self) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreToolUse": [{"matcher": "run_command", "hooks": "not-a-list"}]}}
        )
        assert "hook 'hook': PreToolUse[0]: 'hooks' must be a list of handlers" in errors

    def test_handler_not_dict(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreInvocation": ["not-dict"]}})
        assert "hook 'hook': PreInvocation[0]: handler must be an object" in errors

    def test_handler_missing_command(self) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreInvocation": [{}]}})
        assert "hook 'hook': PreInvocation[0]: missing required field 'command'" in errors

    @pytest.mark.parametrize("bad_cmd", ["", "   ", 123, [], None])
    def test_handler_invalid_command_type_or_empty(self, bad_cmd) -> None:
        errors = validate_antigravity_hooks({"hook": {"PreInvocation": [{"command": bad_cmd}]}})
        assert "hook 'hook': PreInvocation[0]: 'command' must be a non-empty string" in errors

    def test_handler_type_not_string(self) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreInvocation": [{"command": "echo", "type": 123}]}}
        )
        assert "hook 'hook': PreInvocation[0]: 'type' must be a string" in errors

    def test_handler_unsupported_type(self) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreInvocation": [{"command": "echo", "type": "grpc"}]}}
        )
        assert (
            "hook 'hook': PreInvocation[0]: unsupported handler type 'grpc' (only 'command' is supported)"
            in errors
        )

    @pytest.mark.parametrize("bad_timeout", ["10", True, False, 0, -1, -5.5, [], {}])
    def test_handler_invalid_timeout(self, bad_timeout) -> None:
        errors = validate_antigravity_hooks(
            {"hook": {"PreInvocation": [{"command": "echo", "timeout": bad_timeout}]}}
        )
        assert "hook 'hook': PreInvocation[0]: 'timeout' must be a positive number" in errors

    def test_invalid_fixture_hooks(self) -> None:
        fixture_path = (
            FIXTURES_DIR
            / "invalid-plugin"
            / ".agents"
            / "plugins"
            / "invalid-plugin"
            / "hooks.json"
        )
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        errors = validate_antigravity_hooks(data)
        assert "hook 'bad-hook': unknown event 'InvalidEvent'" in errors
        assert any("invalid regex in 'matcher'" in e for e in errors)
        assert (
            "hook 'bad-hook': PreToolUse[0]: hooks[0]: missing required field 'command'" in errors
        )
        assert (
            "hook 'bad-hook': PreToolUse[0]: hooks[0]: unsupported handler type 'unsupported' (only 'command' is supported)"
            in errors
        )


# ==============================================================================
# validate_antigravity_config
# ==============================================================================


class TestValidateAntigravityConfig:
    """Tests for ``validate_antigravity_config``."""

    def test_valid_empty_config(self) -> None:
        assert validate_antigravity_config({}) == []

    def test_valid_fixture_skills_config(self) -> None:
        fixture_path = FIXTURES_DIR / "project-repo" / ".agents" / "skills.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert validate_antigravity_config(data) == []

    def test_valid_fixture_agents_config(self) -> None:
        fixture_path = FIXTURES_DIR / "project-repo" / ".agents" / "agents.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert validate_antigravity_config(data) == []

    def test_valid_dict_configs(self) -> None:
        assert validate_antigravity_config({}) == []
        assert validate_antigravity_config({"entries": []}) == []
        assert validate_antigravity_config({"skills": ["foo"]}) == []

    @pytest.mark.parametrize("invalid_root", [None, "config", 123, [1, 2], True])
    def test_non_dict_root_rejected(self, invalid_root) -> None:
        assert validate_antigravity_config(invalid_root) == [
            "configuration root must be a JSON object"
        ]
