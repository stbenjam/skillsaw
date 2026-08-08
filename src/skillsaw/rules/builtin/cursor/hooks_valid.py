"""
Rule: cursor-hooks-valid
"""

from typing import Any, List

from skillsaw.context import HAS_CURSOR, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import CURSOR_HOOK_EVENTS, CursorHooksBlock

#: Cursor rejects any other value; the field exists so a future format can be
#: told apart from this one.
_SUPPORTED_VERSION = 1


class CursorHooksValidRule(Rule):
    """Validate the structure of .cursor/hooks.json"""

    since = "0.19.0"

    formats = frozenset({HAS_CURSOR})

    @property
    def rule_id(self) -> str:
        return "cursor-hooks-valid"

    @property
    def description(self) -> str:
        return ".cursor/hooks.json must declare version 1 and known hook events with commands"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(CursorHooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
                continue

            data = block.raw_data
            if data is None:
                violations.append(
                    self.violation("hooks.json must be a JSON object", file_path=block.path)
                )
                continue

            violations.extend(self._check_version(data, block))
            violations.extend(self._check_hooks(data, block))

        return violations

    def _check_version(self, data: dict, block: CursorHooksBlock) -> List[RuleViolation]:
        """The version field is required and pins the only shape Cursor reads."""
        if "version" not in data:
            return [
                self.violation(
                    f"Missing 'version' — Cursor requires version {_SUPPORTED_VERSION}",
                    file_path=block.path,
                )
            ]
        version = data["version"]
        # ``True`` is an int in Python but not a version anywhere else.
        if isinstance(version, bool) or version != _SUPPORTED_VERSION:
            return [
                self.violation(
                    f"'version' must be {_SUPPORTED_VERSION}, got " f"{safe_display(str(version))}",
                    file_path=block.path,
                )
            ]
        return []

    def _check_hooks(self, data: dict, block: CursorHooksBlock) -> List[RuleViolation]:
        """Every event must be one Cursor dispatches, holding runnable commands."""
        violations: List[RuleViolation] = []

        if "hooks" not in data:
            return [self.violation("Missing 'hooks' object", file_path=block.path)]

        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            return [self.violation("'hooks' must be a JSON object", file_path=block.path)]

        if not hooks:
            return [
                self.violation(
                    "'hooks' is empty — the file configures nothing",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        for event, entries in hooks.items():
            if event not in CURSOR_HOOK_EVENTS:
                # Not an error: Cursor ignores the key, so the file still
                # loads. It is also never going to run, which is the whole
                # point of reporting it.
                violations.append(
                    self.violation(
                        f"Unknown hook event '{safe_display(str(event))}' — never fires. "
                        f"Valid events: {', '.join(sorted(CURSOR_HOOK_EVENTS))}",
                        file_path=block.path,
                        severity=Severity.WARNING,
                    )
                )
                continue
            violations.extend(self._check_entries(event, entries, block))

        return violations

    def _check_entries(
        self, event: str, entries: Any, block: CursorHooksBlock
    ) -> List[RuleViolation]:
        """Each entry under an event must carry a non-empty command string."""
        if not isinstance(entries, list):
            return [
                self.violation(
                    f"Hook event '{event}' must be an array of hook objects",
                    file_path=block.path,
                )
            ]

        violations: List[RuleViolation] = []
        for index, entry in enumerate(entries):
            where = f"Hook {event}[{index}]"
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"{where} must be an object", file_path=block.path)
                )
                continue
            if "command" not in entry:
                violations.append(
                    self.violation(f"{where} is missing 'command'", file_path=block.path)
                )
                continue
            command = entry["command"]
            # Present is not the same as runnable: ``""`` and ``[]`` both
            # satisfy a key-existence check while naming nothing to spawn.
            if not isinstance(command, str) or not command.strip():
                violations.append(
                    self.violation(
                        f"{where} 'command' must be a non-empty string",
                        file_path=block.path,
                    )
                )

        return violations
