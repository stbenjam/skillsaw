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
    """The allowlist spelling for a handler that runs no shell command.

    A command handler is named by the command it spawns. The other handler
    types run something too — Claude Code dispatches ``http``, ``mcp_tool``,
    ``prompt`` and ``agent`` handlers, and Codex ``mcp_tool`` ones — so a
    policy gate over what fires on a lifecycle event has to name them as
    well, and an allowlist needs a spelling stable enough to enumerate:
    ``mcp_tool:<server>/<tool>``, ``http:<url>``, ``prompt:<prompt>``,
    ``agent:<prompt>``.

    A handler missing its payload falls back to the bare type. That is the
    coarsest possible entry — allowlisting ``http`` permits every payloadless
    ``http`` handler in the repository — but such a handler is malformed and
    the host's own shape rule reports it; inventing a placeholder payload
    would put a spelling in the allowlist that no valid handler ever matches.
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

                    # A handler that spawns no process still fires on the
                    # event: Claude Code calls an ``http`` endpoint, invokes
                    # an ``mcp_tool``, injects a ``prompt``, runs an
                    # ``agent``; Codex invokes an ``mcp_tool``. Skipping them
                    # let a whole class of hook past a policy that says every
                    # hook needs review.
                    #
                    # Reported whatever host owns the file, without asking
                    # whether that host dispatches the type. This is an
                    # inventory of what the repository declares, and the
                    # events here arrive from four hosts plus settings,
                    # frontmatter and Copilot agents — a per-host handler
                    # table threaded through all of them would buy a
                    # narrower report at the cost of a hook going unlisted
                    # every time a host learns a new type. "Muse drops this
                    # handler" is muse-hooks-valid's sentence to say.
                    if not handler.type:
                        # No type at all: no host dispatches it, and the
                        # host's shape rule reports the handler.
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

        # Every host's hooks file is a HooksBlock — Claude, Codex, Muse,
        # Cursor — and each renders its own shape as HookEventConfig.
        hook_blocks = context.lint_tree.find(HooksBlock)
        for block in hook_blocks:
            if block.parse_error:
                continue
            violations.extend(self._check_events(block.events, block.path))

        # Cursor's prompt hooks are the one handler kind ``events`` does not
        # render — its override drops them, so the loop above never sees one
        # and cannot double-report what this loop finds. They are reported
        # here instead because a hook that injects text is still a hook the
        # project did not have before, and by the same ``prompt:<text>``
        # identity a nested-shape prompt handler carries, so one allowlist
        # entry reads the same whichever host's file the prompt sits in.
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
