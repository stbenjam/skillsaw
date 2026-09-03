"""
Rule: hooks-prohibited

Enforces policy controls requiring explicit allowlisting of hook handlers.
Like mcp-prohibited, this rule helps teams monitor and govern automation hooks
across the repository.
"""

from typing import Dict, List

from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    AgentBlock,
    CopilotAgentBlock,
    CursorHooksBlock,
    DevinSkillBlock,
    HookEventConfig,
    HookHandler,
    HooksBlock,
    SettingsBlock,
    SkillBlock,
)


def _handler_identity(handler: HookHandler) -> str:
    """Format an allowlist identifier for non-command hook handlers.

    While command handlers are identified by their command string, non-command
    handlers (such as HTTP requests, MCP tool calls, prompt injections, and subagents)
    use structured identities:
      - mcp_tool:<server>/<tool>
      - http:<url>
      - prompt:<prompt>
      - agent:<prompt>

    If specific payload properties are missing, this falls back to the handler type.
    """
    kind = handler.type
    if kind == "mcp_tool":
        if handler.server and handler.tool:
            return f"mcp_tool:{handler.server}/{handler.tool}"
    elif kind == "http":
        if handler.url:
            return f"http:{handler.url}"
    elif kind in ("prompt", "agent"):
        if handler.prompt:
            return f"{kind}:{handler.prompt}"
    return kind


class HooksProhibitedRule(Rule):
    """Check that projects do not define non-allowlisted hooks."""

    default_enabled = False
    surface_dependencies = ("copilot-agent-valid",)

    since = "0.12.0"

    config_schema = {
        "allowlist": {
            "type": "list",
            "default": [],
            "description": (
                "Hook spellings to permit (exact diagnostic match): a command, or "
                "an identity such as 'mcp_tool:server/tool' for a handler that "
                "runs no command"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "hooks-prohibited"

    @property
    def description(self) -> str:
        return (
            "All hooks are prohibited unless explicitly allowlisted; "
            "catches new or unexpected hooks added to a project"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _is_allowed(self, command: str) -> bool:
        allowlist = self.setting("allowlist")
        return any(command == entry for entry in allowlist)

    def _check_events(
        self,
        events: Dict[str, List[HookEventConfig]],
        file_path,
        line=None,
    ) -> List[RuleViolation]:
        violations = []
        allowlist = self.setting("allowlist")

        for event_type, configs in events.items():
            for cfg in configs:
                for handler in cfg.handlers:
                    if handler.type == "command":
                        for command, source_line in handler.iter_effective_commands():
                            if not command or self._is_allowed(command):
                                continue

                            if allowlist:
                                violations.append(
                                    self.violation(
                                        f"Hook {safe_display(event_type)}: "
                                        f"non-allowlisted command — {safe_display(command)!r}",
                                        file_path=file_path,
                                        line=source_line or line,
                                    )
                                )
                            else:
                                violations.append(
                                    self.violation(
                                        f"Hook {safe_display(event_type)}: hooks are prohibited — "
                                        f"{safe_display(command)!r}",
                                        file_path=file_path,
                                        line=source_line or line,
                                    )
                                )
                        continue

                    # Non-command handlers (HTTP requests, MCP tools, prompts, agents)
                    # also trigger on events, so they are checked against the allowlist.
                    if not handler.type:
                        continue

                    identity = _handler_identity(handler)
                    if self._is_allowed(identity):
                        continue

                    kind = safe_display(handler.type)
                    if allowlist:
                        message = (
                            f"Hook {safe_display(event_type)}: non-allowlisted "
                            f"{kind} hook — {safe_display(identity)!r}"
                        )
                    else:
                        message = (
                            f"Hook {safe_display(event_type)}: {kind} hooks are "
                            f"prohibited — {safe_display(identity)!r}"
                        )
                    violations.append(
                        self.violation(
                            message,
                            file_path=file_path,
                            line=handler.source_line or line,
                        )
                    )
        return violations

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Check all host-specific hook blocks (Claude, Codex, Muse, Cursor),
        # each representing its configuration as HookEventConfig.
        hook_blocks = context.lint_tree.find(HooksBlock)
        for block in hook_blocks:
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        # Cursor prompt hooks are validated here using the prompt:<text> identity
        # format consistent with other prompt hook allowlist entries.
        allowlist = self.setting("allowlist")
        for block in context.lint_tree.find(CursorHooksBlock):
            if block.parse_error:
                continue
            for event_type, _index, prompt in block.prompt_hooks():
                identity = f"prompt:{prompt}"
                if self._is_allowed(identity):
                    continue
                if allowlist:
                    message = (
                        f"Hook {safe_display(event_type)}: non-allowlisted prompt hook — "
                        f"{safe_display(identity)!r}"
                    )
                else:
                    message = (
                        f"Hook {safe_display(event_type)}: prompt hooks are prohibited — "
                        f"{safe_display(identity)!r}"
                    )
                violations.append(self.violation(message, file_path=block.path))

        for block in context.lint_tree.find(SettingsBlock):
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.hooks_events, block.path))

        # Skill and agent frontmatter can declare hooks with the same schema.
        for block in (
            context.lint_tree.find(SkillBlock)
            + context.lint_tree.find(DevinSkillBlock)
            + context.lint_tree.find(AgentBlock)
        ):
            if block.frontmatter_error:
                continue
            events = block.hooks_events
            if events:
                violations.extend(
                    self._check_events(events, block.path, line=block.key_line("hooks"))
                )

        if self.surface_rule_enabled("copilot-agent-valid"):
            for block in context.lint_tree.find(CopilotAgentBlock):
                if block.frontmatter_error:
                    continue
                events = block.hooks_events
                if events:
                    violations.extend(
                        self._check_events(events, block.path, line=block.key_line("hooks"))
                    )

        return violations
