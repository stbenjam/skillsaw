"""
Rules for validating hook configuration
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import HooksBlock

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

        for block in context.lint_tree.find(HooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
                continue

            data = block.raw_data
            if data is None or not isinstance(data, dict):
                violations.append(
                    self.violation("hooks.json must be a JSON object", file_path=block.path)
                )
                continue

            if "hooks" not in data:
                violations.append(
                    self.violation("hooks.json must contain a 'hooks' key", file_path=block.path)
                )
                continue

            raw_hooks = data["hooks"]
            if not isinstance(raw_hooks, dict):
                violations.append(
                    self.violation("'hooks' must be a JSON object", file_path=block.path)
                )
                continue

            for event_type, hook_configs in raw_hooks.items():
                if event_type not in _VALID_HOOK_EVENTS:
                    violations.append(
                        self.violation(
                            f"Unknown event type '{event_type}'. Valid types: {', '.join(sorted(_VALID_HOOK_EVENTS))}",
                            file_path=block.path,
                        )
                    )

                if not isinstance(hook_configs, list):
                    violations.append(
                        self.violation(
                            f"Event '{event_type}' must have an array of hook configurations",
                            file_path=block.path,
                        )
                    )
                    continue

                for idx, hook_config in enumerate(hook_configs):
                    if not isinstance(hook_config, dict):
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}]' configuration must be an object",
                                file_path=block.path,
                            )
                        )
                        continue

                    if "hooks" not in hook_config:
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}]' must have a 'hooks' array",
                                file_path=block.path,
                            )
                        )
                        continue

                    hook_list = hook_config["hooks"]
                    if not isinstance(hook_list, list):
                        violations.append(
                            self.violation(
                                f"Event '{event_type}[{idx}].hooks' must be an array",
                                file_path=block.path,
                            )
                        )
                        continue

                    for hook_idx, hook in enumerate(hook_list):
                        if not isinstance(hook, dict):
                            violations.append(
                                self.violation(
                                    f"Event '{event_type}[{idx}].hooks[{hook_idx}]' must be an object",
                                    file_path=block.path,
                                )
                            )
                            continue

                        if "type" not in hook:
                            violations.append(
                                self.violation(
                                    f"Event '{event_type}[{idx}].hooks[{hook_idx}]' must have a 'type' field",
                                    file_path=block.path,
                                )
                            )
                            continue

                        hook_type = hook["type"]
                        hook_path = f"{event_type}[{idx}].hooks[{hook_idx}]"

                        if hook_type not in _VALID_HOOK_TYPES:
                            violations.append(
                                self.violation(
                                    f"Event '{hook_path}' has invalid type '{hook_type}'. "
                                    f"Valid types: {', '.join(sorted(_VALID_HOOK_TYPES))}",
                                    file_path=block.path,
                                )
                            )
                            continue

                        for field, expected_type in _TYPE_REQUIRED_FIELDS[hook_type].items():
                            if field not in hook:
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' of type '{hook_type}' "
                                        f"requires a '{field}' field",
                                        file_path=block.path,
                                    )
                                )
                            elif not _check_field_type(hook[field], expected_type):
                                type_name = _format_type_name(expected_type)
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' field '{field}' "
                                        f"must be a {type_name}",
                                        file_path=block.path,
                                    )
                                )

                        for field in hook:
                            if field in _TYPE_SPECIFIC_FIELDS:
                                valid_types = _TYPE_SPECIFIC_FIELDS[field]
                                if hook_type not in valid_types:
                                    violations.append(
                                        self.violation(
                                            f"Event '{hook_path}' field '{field}' "
                                            f"is only valid on types: "
                                            f"{', '.join(sorted(valid_types))}",
                                            file_path=block.path,
                                            severity=Severity.WARNING,
                                        )
                                    )

                        for field, expected_type in _OPTIONAL_FIELD_TYPES.items():
                            if field not in hook:
                                continue
                            if not _check_field_type(hook[field], expected_type):
                                type_name = _format_type_name(expected_type)
                                violations.append(
                                    self.violation(
                                        f"Event '{hook_path}' field '{field}' "
                                        f"must be a {type_name}",
                                        file_path=block.path,
                                    )
                                )

        return violations
