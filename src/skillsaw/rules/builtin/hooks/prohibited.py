"""
Rule: hooks-prohibited

Policy rule: hooks are not allowed unless explicitly allowlisted.
Mirrors the mcp-prohibited pattern.
"""

from typing import Dict, List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    HookEventConfig,
    HooksBlock,
    SettingsBlock,
)


class HooksProhibitedRule(Rule):
    """Check that projects do not define non-allowlisted hooks."""

    since = "0.12.0"

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": "Hook commands to permit (exact match)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "hooks-prohibited"

    @property
    def description(self) -> str:
        return (
            "All hook commands are prohibited unless explicitly allowlisted; "
            "catches new or unexpected hooks added to a project"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _is_allowed(self, command: str) -> bool:
        allowlist = self.config.get("allowlist", [])
        return any(command == entry for entry in allowlist)

    def _check_events(
        self,
        events: Dict[str, List[HookEventConfig]],
        file_path,
    ) -> List[RuleViolation]:
        violations = []
        allowlist = self.config.get("allowlist", [])

        for event_type, configs in events.items():
            for cfg in configs:
                for handler in cfg.handlers:
                    if handler.type != "command" or not handler.command:
                        continue
                    if self._is_allowed(handler.command):
                        continue

                    if allowlist:
                        violations.append(
                            self.violation(
                                f"Hook {event_type}: non-allowlisted command — "
                                f"{handler.command!r}",
                                file_path=file_path,
                            )
                        )
                    else:
                        violations.append(
                            self.violation(
                                f"Hook {event_type}: hooks are prohibited — "
                                f"{handler.command!r}",
                                file_path=file_path,
                            )
                        )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(HooksBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.hooks_events, block.path))

        return violations
