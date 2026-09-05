"""The verbose permission shape consumed by Grok's workspace resolver.

This is workspace/permission/types.rs, not the shell config-types sibling:
the workspace consumer also recognizes websearch and permission policy fields.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from skillsaw.formats.grok_config import struct_fields, unit_enum_value

ACTIONS = frozenset({"allow", "deny", "ask"})
TOOLS = frozenset(
    {
        "any",
        "bash",
        "edit",
        "read",
        "grep",
        "mcp",
        "webfetch",
        "websearch",
        "agent_message",
        "agentmessage",
    }
)
PATTERN_MODES = frozenset({"glob", "domain"})
PROMPT_POLICIES = frozenset({"ask", "deny", "auto", "allow"})


def permission_fields(value: Any) -> Any:
    return struct_fields(value, ("rules", "prompt_policy", "default_mode_configured"))


def rule_fields(value: Any) -> Any:
    # Unlike named Option<String>, the positional pattern slot is required.
    return struct_fields(value, ("action", "tool", "pattern", "pattern_mode"), 3)


def _enum_problem(field: str, value: Any, choices: frozenset) -> Optional[str]:
    if unit_enum_value(value) in choices:
        return None
    return f"'{field}' must be one of " + ", ".join(sorted(choices))


def verbose_permission_problems(table: Mapping[str, Any]) -> List[str]:
    """Reasons the workspace decoder drops the entire verbose rule list."""
    problems = []
    if "prompt_policy" in table:
        problem = _enum_problem("prompt_policy", table["prompt_policy"], PROMPT_POLICIES)
        if problem:
            problems.append(problem)
    if "default_mode_configured" in table and not isinstance(
        table["default_mode_configured"], bool
    ):
        problems.append("'default_mode_configured' must be a boolean")
    rules = table.get("rules", [])
    if not isinstance(rules, list):
        return problems
    for position, value in enumerate(rules, 1):
        rule = rule_fields(value)
        if not isinstance(rule, dict):
            continue  # The caller owns the array's table shape.
        prefix = f"entry {position}: "
        if "action" not in rule:
            problems.append(prefix + "missing required 'action'")
        for field, choices in (
            ("action", ACTIONS),
            ("tool", TOOLS),
            ("pattern_mode", PATTERN_MODES),
        ):
            if field in rule:
                problem = _enum_problem(field, rule[field], choices)
                if problem:
                    problems.append(prefix + problem)
        if "pattern" in rule and not isinstance(rule["pattern"], str):
            problems.append(prefix + "'pattern' must be a string")
    return problems
