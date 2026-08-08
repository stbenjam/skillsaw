"""
Rule: hooks-prohibited

Policy rule: hooks are not allowed unless explicitly allowlisted.
Mirrors the mcp-prohibited pattern.
"""

from typing import Dict, List

from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CursorHooksBlock,
    HookEventConfig,
    HooksBlock,
    SettingsBlock,
    SkillBlock,
)


class HooksProhibitedRule(Rule):
    """Check that projects do not define non-allowlisted hooks."""

    default_enabled = False

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
        line=None,
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
                                f"Hook {safe_display(event_type)}: non-allowlisted command — "
                                f"{safe_display(handler.command)!r}",
                                file_path=file_path,
                                line=line,
                            )
                        )
                    else:
                        violations.append(
                            self.violation(
                                f"Hook {safe_display(event_type)}: hooks are prohibited — "
                                f"{safe_display(handler.command)!r}",
                                file_path=file_path,
                                line=line,
                            )
                        )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # CursorHooksBlock renders its flatter shape as HookEventConfig too.
        hook_blocks = context.lint_tree.find(HooksBlock) + context.lint_tree.find(CursorHooksBlock)
        for block in hook_blocks:
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        # A Cursor prompt hook runs no command, so it carries nothing an
        # allowlist of commands could match — but this rule is a policy gate
        # over what fires on a lifecycle event, not a command scanner, and a
        # hook that injects text is still a hook the project did not have
        # before.
        for block in context.lint_tree.find(CursorHooksBlock):
            if block.parse_error:
                continue
            for event_type, _index, prompt in block.prompt_hooks():
                violations.append(
                    self.violation(
                        f"Hook {safe_display(event_type)}: prompt hooks are prohibited — "
                        f"{safe_display(prompt)!r}",
                        file_path=block.path,
                    )
                )

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.hooks_events, block.path))

        # Skill and agent frontmatter can declare hooks with the same schema.
        for block in context.lint_tree.find(SkillBlock) + context.lint_tree.find(AgentBlock):
            if block.frontmatter_error:
                continue
            events = block.hooks_events
            if events:
                violations.extend(
                    self._check_events(events, block.path, line=block.key_line("hooks"))
                )

        return violations
