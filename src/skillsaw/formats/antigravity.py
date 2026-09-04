r"""Google Antigravity repository-context vocabulary, in one place.

Google Antigravity is an agentic coding assistant and execution platform.
A workspace or repository configures it through ``.agents/`` or ``.agent/``:
portable Agent Skills in ``skills/``, rules in ``rules/**/*.md``, configuration
registries in ``skills.json``, ``agents.json``, and ``rules.json``, lifecycle
hooks in ``hooks.json``, MCP servers in ``mcp_config.json``, and plugins in
``plugins/<name>/``.

Sources:

* Google Antigravity Customization System specification (September 2026).
* Antigravity extension manifest schema and hook handler contracts.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from skillsaw.diagnostics import safe_display

ANTIGRAVITY_CONFIG_DIR_NAMES = (".agents", ".agent")

PLUGIN_MANIFEST = "plugin.json"
HOOKS_FILENAME = "hooks.json"
MCP_CONFIG_FILENAME = "mcp_config.json"
SKILLS_CONFIG_FILENAME = "skills.json"
AGENTS_CONFIG_FILENAME = "agents.json"
RULES_CONFIG_FILENAME = "rules.json"

PLUGIN_KNOWN_FIELDS = frozenset({"$schema", "name", "description", "version", "author", "disabled"})

TOOL_HOOK_EVENTS = frozenset({"PreToolUse", "PostToolUse"})
NON_TOOL_HOOK_EVENTS = frozenset({"PreInvocation", "PostInvocation", "Stop"})
HOOK_EVENTS = TOOL_HOOK_EVENTS | NON_TOOL_HOOK_EVENTS

VALID_HOOK_HANDLER_TYPES = frozenset({"command"})

_PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z0-9-_]+$")


def validate_antigravity_manifest(data: Any) -> List[str]:
    """Validate parsed data from an Antigravity ``plugin.json`` manifest."""
    if not isinstance(data, dict):
        return ["manifest root must be a JSON object"]

    errors: List[str] = []
    unknown = set(data) - PLUGIN_KNOWN_FIELDS
    for field in sorted(unknown):
        errors.append(f"unknown field '{safe_display(field)}'")

    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append("'name' must be a non-empty string")
        elif not _PLUGIN_NAME_RE.match(name):
            errors.append(
                f"invalid plugin name '{safe_display(name)}' (must contain only alphanumeric characters, dashes, or underscores)"
            )

    if "description" in data:
        description = data["description"]
        if not isinstance(description, str):
            errors.append("'description' must be a string")

    if "version" in data:
        version = data["version"]
        if not isinstance(version, str) or not version.strip():
            errors.append("'version' must be a non-empty string")

    if "disabled" in data:
        disabled = data["disabled"]
        if not isinstance(disabled, bool):
            errors.append("'disabled' must be a boolean")

    if "author" in data:
        author = data["author"]
        if isinstance(author, dict):
            if "name" in author and not isinstance(author["name"], str):
                errors.append("'author.name' must be a string")
        elif not isinstance(author, str):
            errors.append("'author' must be an object or a string")

    return errors


def validate_antigravity_hooks(data: Any, extra_events: Optional[Set[str]] = None) -> List[str]:
    """Validate parsed data from an Antigravity ``hooks.json`` document."""
    if not isinstance(data, dict):
        return ["hooks root must be a JSON object"]

    errors: List[str] = []
    allowed_events = HOOK_EVENTS | (extra_events or frozenset())

    for hook_name, hook_spec in data.items():
        prefix = f"hook '{safe_display(hook_name)}':"
        if not isinstance(hook_spec, dict):
            errors.append(f"{prefix} hook configuration must be a JSON object")
            continue

        if "enabled" in hook_spec and not isinstance(hook_spec["enabled"], bool):
            errors.append(f"{prefix} 'enabled' must be a boolean")

        for key, value in hook_spec.items():
            if key == "enabled":
                continue
            if key not in allowed_events:
                errors.append(f"{prefix} unknown event '{safe_display(key)}'")
                continue

            if not isinstance(value, list):
                errors.append(f"{prefix} event '{safe_display(key)}' must be a list")
                continue

            if key in TOOL_HOOK_EVENTS:
                # Grouped: [{matcher, hooks: [{command, type?, timeout?}]}]
                for idx, matcher_entry in enumerate(value):
                    entry_prefix = f"{prefix} {key}[{idx}]:"
                    if not isinstance(matcher_entry, dict):
                        errors.append(f"{entry_prefix} matcher entry must be an object")
                        continue

                    if "matcher" in matcher_entry:
                        matcher = matcher_entry["matcher"]
                        if not isinstance(matcher, str):
                            errors.append(f"{entry_prefix} 'matcher' must be a string")
                        else:
                            try:
                                re.compile(matcher)
                            except (re.error, RecursionError, OverflowError) as err:
                                errors.append(
                                    f"{entry_prefix} invalid regex in 'matcher': {safe_display(err)}"
                                )

                    if "hooks" not in matcher_entry:
                        errors.append(f"{entry_prefix} missing required field 'hooks'")
                    elif not isinstance(matcher_entry["hooks"], list):
                        errors.append(f"{entry_prefix} 'hooks' must be a list of handlers")
                    else:
                        for h_idx, handler in enumerate(matcher_entry["hooks"]):
                            h_prefix = f"{entry_prefix} hooks[{h_idx}]:"
                            _validate_hook_handler(handler, h_prefix, errors)
            else:
                # Non-tool events: list of handler objects directly
                for idx, handler in enumerate(value):
                    h_prefix = f"{prefix} {key}[{idx}]:"
                    _validate_hook_handler(handler, h_prefix, errors)

    return errors


def _validate_hook_handler(handler: Any, prefix: str, errors: List[str]) -> None:
    if not isinstance(handler, dict):
        errors.append(f"{prefix} handler must be an object")
        return

    if "command" not in handler:
        errors.append(f"{prefix} missing required field 'command'")
    elif not isinstance(handler["command"], str) or not handler["command"].strip():
        errors.append(f"{prefix} 'command' must be a non-empty string")

    if "type" in handler:
        type_val = handler["type"]
        if not isinstance(type_val, str):
            errors.append(f"{prefix} 'type' must be a string")
        elif type_val not in VALID_HOOK_HANDLER_TYPES:
            errors.append(
                f"{prefix} unsupported handler type '{safe_display(type_val)}' (only 'command' is supported)"
            )

    if "timeout" in handler:
        timeout = handler["timeout"]
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            errors.append(f"{prefix} 'timeout' must be a positive number")


def validate_antigravity_config(data: Any) -> List[str]:
    """Validate parsed data from an Antigravity configuration file (skills.json, agents.json, rules.json)."""
    if not isinstance(data, dict):
        return ["configuration root must be a JSON object"]
    return []
