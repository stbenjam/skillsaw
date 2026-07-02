"""
Rule: agent-frontmatter-values

Validates the values of documented agent frontmatter fields: enum fields
must use a documented value, typed fields must have the right type, and
plugin-shipped agents must not declare fields Claude Code silently
ignores for security reasons (hooks, mcpServers, permissionMode).
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import AgentBlock

# Documented value sets for enum-valued agent frontmatter fields.
_ENUM_FIELDS = {
    "permissionMode": {
        "default",
        "acceptEdits",
        "auto",
        "dontAsk",
        "bypassPermissions",
        "plan",
    },
    "memory": {"user", "project", "local"},
    "effort": {"low", "medium", "high", "xhigh", "max"},
    "isolation": {"worktree"},
    "color": {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"},
}

# Fields silently ignored on plugin-shipped agents for security reasons.
_PLUGIN_PROHIBITED_FIELDS = ("hooks", "mcpServers", "permissionMode")


class AgentFrontmatterValuesRule(Rule):
    """Check documented agent frontmatter fields carry valid values."""

    since = "0.15.0"

    @property
    def rule_id(self) -> str:
        return "agent-frontmatter-values"

    @property
    def description(self) -> str:
        return (
            "Agent frontmatter enum fields (permissionMode, memory, effort, "
            "isolation, color) must use documented values, and plugin-shipped "
            "agents must not declare hooks, mcpServers, or permissionMode"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(AgentBlock):
            if block.frontmatter_error or not block.has_frontmatter:
                continue

            for field_name, valid_values in _ENUM_FIELDS.items():
                value = block.field_value(field_name)
                if value is None:
                    continue
                if not isinstance(value, str) or value not in valid_values:
                    violations.append(
                        self.violation(
                            f"'{field_name}: {value}' is not a documented value. "
                            f"Valid values: {', '.join(sorted(valid_values))}",
                            block=block,
                            line=block.key_line(field_name),
                        )
                    )

            background = block.field_value("background")
            if background is not None and not isinstance(background, bool):
                violations.append(
                    self.violation(
                        f"'background: {background}' must be a boolean",
                        block=block,
                        line=block.key_line("background"),
                    )
                )

            max_turns = block.field_value("maxTurns")
            if max_turns is not None and (
                isinstance(max_turns, bool) or not isinstance(max_turns, int)
            ):
                violations.append(
                    self.violation(
                        f"'maxTurns: {max_turns}' must be an integer",
                        block=block,
                        line=block.key_line("maxTurns"),
                    )
                )

            # Agents inside .claude/ are project agents; everything else
            # discovered by the lint tree ships with a plugin, where these
            # fields are ignored for security reasons.
            if ".claude" in block.path.parts:
                continue
            for field_name in _PLUGIN_PROHIBITED_FIELDS:
                if block.field(field_name) is not None:
                    violations.append(
                        self.violation(
                            f"'{field_name}' is not supported on plugin-shipped "
                            "agents and is silently ignored by Claude Code",
                            block=block,
                            line=block.key_line(field_name),
                        )
                    )

        return violations
