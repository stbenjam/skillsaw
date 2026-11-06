"""
Rule: zcode-hooks-valid

Checks the hooks a ZCode plugin ships — ``hooks/hooks.json``, a file the
manifest names in ``hooks``, or an inline ``hooks`` object — against the
events and handler shapes ZCode's plugin loader accepts.
"""

from typing import List

from skillsaw.blocks import ZCodeInlineHooksBlock, ZCodePluginHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.zcode import HOOK_EVENTS
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import ZCODE_PLUGIN_REPO_TYPES, matcher_group_problems


class ZCodeHooksValidRule(Rule):
    """Check that ZCode plugin hooks use events and handlers ZCode runs"""

    since = "0.23.0"

    repo_types = ZCODE_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-hooks-valid"

    @property
    def description(self) -> str:
        return "ZCode plugin hooks must use ZCode's events and command/process handlers"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(ZCodePluginHooksBlock):
            inline = isinstance(block, ZCodeInlineHooksBlock)
            source = "the manifest's inline 'hooks'" if inline else block.path.name
            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid JSON: {block.parse_error}; ZCode skips every hook in this file",
                        file_path=block.path,
                    )
                )
                continue
            data = block.raw_data
            events = data.get("hooks") if isinstance(data, dict) else None
            if not isinstance(events, dict):
                violations.append(
                    self.violation(
                        "Hooks file must contain a 'hooks' object mapping events to matcher "
                        "groups; ZCode skips every hook in this file",
                        file_path=block.path,
                    )
                )
                continue
            for event, groups in events.items():
                if event not in HOOK_EVENTS:
                    violations.append(
                        self.violation(
                            f"Event {safe_display(event)!r} in {source} is not one ZCode runs, so its hooks "
                            f"are skipped. ZCode's events: {', '.join(sorted(HOOK_EVENTS))}",
                            file_path=block.path,
                            severity=self.scope_severity(Severity.WARNING),
                        )
                    )
                    continue
                if not isinstance(groups, list):
                    violations.append(
                        self.violation(
                            f"Event {safe_display(event)!r} in {source} must be an array of matcher groups; "
                            "ZCode skips the event",
                            file_path=block.path,
                        )
                    )
                    continue
                for index, group in enumerate(groups):
                    problems = matcher_group_problems(group, project=False)
                    if problems:
                        violations.append(
                            self.violation(
                                f"{safe_display(event)}[{index}] in {source}: {'; '.join(problems)}. "
                                "ZCode drops this whole matcher group",
                                file_path=block.path,
                            )
                        )
        return violations
