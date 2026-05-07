"""
Rules for validating hook configuration
"""

import json
from typing import List, Dict, Any

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext

# Valid hook event types
_VALID_HOOK_EVENTS = {
    "SessionStart",
    "Setup",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "PreToolUse",
    "PermissionRequest",
    "PermissionDenied",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "Elicitation",
    "ElicitationResult",
    "SessionEnd",
}

# Valid hook handler types
_VALID_HOOK_TYPES = {"command", "http", "mcp_tool", "prompt", "agent"}

# Required fields per handler type
_TYPE_REQUIRED_FIELDS = {
    "command": {"command": str},
    "http": {"url": str},
    "mcp_tool": {"server": str, "tool": str},
    "prompt": {"prompt": str},
    "agent": {"prompt": str},
}

# Fields restricted to specific handler types (field -> set of valid types)
_TYPE_SPECIFIC_FIELDS = {
    "command": {"command"},
    "async": {"command"},
    "asyncRewake": {"command"},
    "shell": {"command"},
    "url": {"http"},
    "headers": {"http"},
    "allowedEnvVars": {"http"},
    "server": {"mcp_tool"},
    "tool": {"mcp_tool"},
    "input": {"mcp_tool"},
    "prompt": {"prompt", "agent"},
    "model": {"prompt", "agent"},
}

# Common optional field type validation
_OPTIONAL_FIELD_TYPES = {
    "timeout": (int, float),
    "async": bool,
    "asyncRewake": bool,
    "once": bool,
    "if": str,
    "statusMessage": str,
    "shell": str,
    "headers": dict,
    "allowedEnvVars": list,
    "input": dict,
}


def _check_field_type(value, expected_type):
    """Check if value matches expected type, treating bool as distinct from int."""
    if expected_type is bool:
        return isinstance(value, bool)
    return isinstance(value, expected_type) and not isinstance(value, bool)


def _format_type_name(expected_type):
    """Format expected type for error messages."""
    if isinstance(expected_type, tuple):
        return "/".join(t.__name__ for t in expected_type)
    return expected_type.__name__


class HooksJsonValidRule(Rule):
    """Check that hooks.json is valid JSON with proper structure"""

    @property
    def rule_id(self) -> str:
        return "hooks-json-valid"

    @property
    def description(self) -> str:
        return "hooks.json must be valid JSON with proper hook configuration structure"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            hooks_dir = plugin_path / "hooks"
            if not hooks_dir.exists():
                continue

            hooks_json = hooks_dir / "hooks.json"
            if not hooks_json.exists():
                continue

            # Try to parse JSON
            try:
                with open(hooks_json, "r") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                violations.append(self.violation(f"Invalid JSON: {e}", file_path=hooks_json))
                continue
            except IOError as e:
                violations.append(self.violation(f"Failed to read file: {e}", file_path=hooks_json))
                continue

            # Validate structure
            if not isinstance(data, dict):
                violations.append(
                    self.violation("hooks.json must be a JSON object", file_path=hooks_json)
                )
                continue

            if "hooks" not in data:
                violations.append(
                    self.violation("hooks.json must contain a 'hooks' key", file_path=hooks_json)
                )
                continue

            hooks = data["hooks"]
            if not isinstance(hooks, dict):
                violations.append(
                    self.violation("'hooks' must be a JSON object", file_path=hooks_json)
                )
                continue

            # Validate event types
            for event_type, hook_configs in hooks.items():
                if event_type not in _VALID_HOOK_EVENTS:
                    violations.append(
                        self.violation(
                            f"Unknown event type '{event_type}'. Valid types: {', '.join(sorted(_VALID_HOOK_EVENTS))}",
                            file_path=hooks_json,
                        )
                    )

                if not isinstance(hook_configs, list):
                    violations.append(
                        self.violation(
                            f"Event '{event_type}' must have an array of hook configurations",
                            file_path=hooks_json,
                        )
                    )
                    continue

                for idx, hook_config in enumerate(hook_configs):
                    if not isinstance(hook_config, dict):
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}]' configuration must be an object",
                                file_path=hooks_json,
                            )
                        )
                        continue

                    # Validate hook configuration has required 'hooks' array
                    if "hooks" not in hook_config:
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}]' must have a 'hooks' array",
                                file_path=hooks_json,
                            )
                        )
                        continue

                    hook_list = hook_config["hooks"]
                    if not isinstance(hook_list, list):
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}].hooks' must be an array",
                                file_path=hooks_json,
                            )
                        )
                        continue

                    # Validate each hook has a type
                    for hook_idx, hook in enumerate(hook_list):
                        if not isinstance(hook, dict):
                            violations.append(
                                self.violation(
                                    f"Event '{event_type}[{idx}].hooks[{hook_idx}]' must be an object",
                                    file_path=hooks_json,
                                )
                            )
                            continue

                        if "type" not in hook:
                            violations.append(
                                self.violation(
                                    f"Event '{event_type}[{idx}].hooks[{hook_idx}]' must have a 'type' field",
                                    file_path=hooks_json,
                                )
                            )
                            continue

                        hook_type = hook["type"]
                        hook_path = f"{event_type}[{idx}].hooks[{hook_idx}]"

                        # Validate type value
                        if hook_type not in _VALID_HOOK_TYPES:
                            violations.append(
                                self.violation(
                                    f"Event '{hook_path}' has invalid type '{hook_type}'. "
                                    f"Valid types: {', '.join(sorted(_VALID_HOOK_TYPES))}",
                                    file_path=hooks_json,
                                )
                            )
                            continue

                        # Validate type-specific required fields
                        for field, expected_type in _TYPE_REQUIRED_FIELDS[hook_type].items():
                            if field not in hook:
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' of type '{hook_type}' "
                                        f"requires a '{field}' field",
                                        file_path=hooks_json,
                                    )
                                )
                            elif not _check_field_type(hook[field], expected_type):
                                type_name = _format_type_name(expected_type)
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' field '{field}' "
                                        f"must be a {type_name}",
                                        file_path=hooks_json,
                                    )
                                )

                        # Validate type-specific field restrictions (WARNING)
                        for field in hook:
                            if field in _TYPE_SPECIFIC_FIELDS:
                                valid_types = _TYPE_SPECIFIC_FIELDS[field]
                                if hook_type not in valid_types:
                                    violations.append(
                                        self.violation(
                                            f"Event '{hook_path}' field '{field}' "
                                            f"is only valid on types: "
                                            f"{', '.join(sorted(valid_types))}",
                                            file_path=hooks_json,
                                            severity=Severity.WARNING,
                                        )
                                    )

                        # Validate common optional field types
                        for field, expected_type in _OPTIONAL_FIELD_TYPES.items():
                            if field not in hook:
                                continue
                            if not _check_field_type(hook[field], expected_type):
                                type_name = _format_type_name(expected_type)
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' field '{field}' "
                                        f"must be a {type_name}",
                                        file_path=hooks_json,
                                    )
                                )

        return violations
