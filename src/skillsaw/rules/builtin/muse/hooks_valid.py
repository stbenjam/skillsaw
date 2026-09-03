"""
Rule: muse-hooks-valid
"""

import re
from typing import Any, Dict, List, Optional, Set

from skillsaw.context import HAS_MUSE, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import muse
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import MuseHooksBlock

#: Matchers Muse treats as "everything" rather than compiling as a pattern.
#: ``"*"`` is not a valid regex — reporting it would be a false positive on
#: the spelling Muse's own documentation uses for a catch-all.
_WILDCARD_MATCHERS = frozenset({"", "*"})

#: Handler fields with a check of their own, so the generic field-type loop
#: does not report the same defect twice.
_SELF_CHECKED_HANDLER_FIELDS = frozenset({"type", "command"})

#: The handler types other hosts define, named so the diagnostic can say why
#: Muse drops them rather than only that it does.
_OTHER_HOST_HANDLER_TYPES = frozenset({"http", "prompt", "agent", "mcp_tool"})

#: The handler types Muse runs, rendered for a message.
_ACCEPTED_TYPES = ", ".join(f"'{name}'" for name in sorted(muse.HOOK_HANDLER_TYPES))

#: The keys a matcher group may carry, rendered for a message.
_GROUP_FIELDS = " and ".join(f"'{name}'" for name in sorted(muse.MATCHER_GROUP_FIELDS))

#: Where the whole-file verdict is spelled. Muse rejects the file, loads no
#: hooks from it, and prints nothing — so every group-level defect costs the
#: hooks that were fine.
_WHOLE_FILE = "Muse rejects the whole file, so no hook in it runs"

#: Where the handler-level verdict is spelled: siblings still run.
_DROPPED = "Muse drops this handler, so it never runs"


class MuseHooksValidRule(Rule):
    """Validate the structure of .muse/hooks.json"""

    since = "0.20.0"

    formats = frozenset({HAS_MUSE})

    config_schema = {
        "extra-events": {
            "type": "list",
            "default": [],
            "description": (
                "Additional hook event names to accept, for events newer than "
                "this skillsaw release"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "muse-hooks-valid"

    @property
    def description(self) -> str:
        return ".muse/hooks.json must use Muse's events, matcher groups and handler fields"

    def default_severity(self) -> Severity:
        # Every defect this rule reports is a hook that does not run, and
        # Muse says nothing about any of them in a headless run.
        return Severity.ERROR

    def _known_events(self) -> Set[str]:
        """Muse's event names plus any the project declares.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would raise
        ``TypeError`` and cost every structural finding in the file over one
        bad config line; a value of the wrong shape contributes no events.
        """
        extra = self.setting("extra-events") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return set(muse.HOOK_EVENTS)
        return set(muse.HOOK_EVENTS) | {event for event in extra if isinstance(event, str)}

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(MuseHooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid JSON: {block.parse_error} — Muse loads no hooks from this file",
                        file_path=block.path,
                    )
                )
                continue

            data = block.raw_data
            if data is None:
                violations.append(
                    self.violation(
                        "hooks.json must be a JSON object — Muse loads no hooks from this file",
                        file_path=block.path,
                    )
                )
                continue

            violations.extend(self._check_hooks(data, block))

        return violations

    def _check_hooks(self, data: Dict[str, Any], block: MuseHooksBlock) -> List[RuleViolation]:
        """``hooks`` holds every event Muse dispatches on; other keys are ignored."""
        if "hooks" not in data:
            return [
                self.violation(
                    "Missing 'hooks' object — Muse loads no hooks from this file",
                    file_path=block.path,
                )
            ]

        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            return [
                self.violation(
                    "'hooks' must be a JSON object — Muse loads no hooks from this file",
                    file_path=block.path,
                )
            ]

        if not hooks:
            return [
                self.violation(
                    "'hooks' is empty — the file configures nothing",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        violations: List[RuleViolation] = []
        known = self._known_events()
        for event, groups in hooks.items():
            if event not in known:
                # A warning, not an error: Muse skips the entry and loads the
                # rest of the file, and its event set grows between skillsaw
                # releases. ``extra-events`` is named so a false positive has
                # a same-day remedy.
                violations.append(
                    self.violation(
                        f"Unknown hook event '{safe_display(str(event))}' — Muse dispatches "
                        "no such event, so this entry never fires. Event names are "
                        "case-sensitive; if Muse added this one after this skillsaw "
                        "release, list it under muse-hooks-valid 'extra-events'.",
                        file_path=block.path,
                        severity=Severity.WARNING,
                    )
                )
                # Fall through rather than skipping. The warning already says
                # the name may be an event this release has not heard of; if
                # it is, its entries are live configuration and deserve the
                # same shape checks. Skipping them would leave a malformed
                # group invisible until the author set ``extra-events``.
            violations.extend(self._check_groups(str(event), groups, block))

        return violations

    def _check_groups(self, event: str, groups: Any, block: MuseHooksBlock) -> List[RuleViolation]:
        """Each event holds an array of matcher groups, or the file is rejected."""
        if not isinstance(groups, list):
            return [
                self.violation(
                    f"Hook event '{safe_display(event)}' must be an array of matcher "
                    f"groups — {_WHOLE_FILE}",
                    file_path=block.path,
                )
            ]

        if not groups:
            return [
                self.violation(
                    f"Hook event '{safe_display(event)}' has an empty array — "
                    "it configures no hook",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        violations: List[RuleViolation] = []
        for index, group in enumerate(groups):
            where = f"Hook {safe_display(event)}[{index}]"
            if not isinstance(group, dict):
                violations.append(
                    self.violation(
                        f"{where} must be an object — {_WHOLE_FILE}",
                        file_path=block.path,
                    )
                )
                continue
            violations.extend(self._check_group(where, group, block))

        return violations

    def _check_group(
        self, where: str, group: Dict[str, Any], block: MuseHooksBlock
    ) -> List[RuleViolation]:
        """A matcher group carries a ``matcher`` and a ``hooks`` array, nothing else."""
        violations: List[RuleViolation] = []

        for key in group:
            if key not in muse.MATCHER_GROUP_FIELDS:
                violations.append(
                    self.violation(
                        f"{where} has unknown field '{safe_display(str(key))}', and a matcher "
                        f"group may carry only {_GROUP_FIELDS} — {_WHOLE_FILE}",
                        file_path=block.path,
                    )
                )

        violations.extend(self._check_matcher(where, group, block))

        if "hooks" not in group:
            violations.append(
                self.violation(
                    f"{where} is missing 'hooks' — {_WHOLE_FILE}",
                    file_path=block.path,
                )
            )
            return violations

        handlers = group["hooks"]
        if not isinstance(handlers, list):
            violations.append(
                self.violation(
                    f"{where} 'hooks' must be an array of handlers — {_WHOLE_FILE}",
                    file_path=block.path,
                )
            )
            return violations

        for index, handler in enumerate(handlers):
            violations.extend(self._check_handler(f"{where}.hooks[{index}]", handler, block))

        return violations

    def _check_matcher(
        self, where: str, group: Dict[str, Any], block: MuseHooksBlock
    ) -> List[RuleViolation]:
        """``matcher`` is an optional regex; a non-string one rejects the file."""
        if "matcher" not in group:
            return []

        matcher = group["matcher"]
        if not isinstance(matcher, str):
            return [
                self.violation(
                    f"{where} 'matcher' must be a string, got {type(matcher).__name__} — "
                    f"{_WHOLE_FILE}",
                    file_path=block.path,
                )
            ]

        if matcher in _WILDCARD_MATCHERS:
            return []

        try:
            re.compile(matcher)
        except re.error as err:
            # A warning, not an error: Muse's matcher is a Rust regex and
            # Python's dialect differs at the edges, so a pattern Python
            # rejects may still be one Muse compiles.
            return [
                self.violation(
                    f"{where} 'matcher' {safe_display(repr(matcher))} is not a valid "
                    f"regex — {err.msg}; Muse skips this hook",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]
        return []

    def _check_handler(
        self, where: str, handler: Any, block: MuseHooksBlock
    ) -> List[RuleViolation]:
        """One handler: a command, its type, and the fields Muse knows."""
        if not isinstance(handler, dict):
            return [
                self.violation(
                    f"{where} must be an object — {_DROPPED}",
                    file_path=block.path,
                )
            ]

        type_violation = self._check_handler_type(where, handler, block)
        if type_violation is not None:
            # The handler is already dropped on its type; reporting its other
            # fields as well would be several findings for one dead handler.
            return [type_violation]

        violations = self._check_command(where, handler, block)
        violations.extend(self._check_handler_fields(where, handler, block))
        return violations

    def _check_handler_type(
        self, where: str, handler: Dict[str, Any], block: MuseHooksBlock
    ) -> Optional[RuleViolation]:
        """``type`` is required and Muse runs exactly one kind of handler."""
        if "type" not in handler:
            return self.violation(
                f"{where} is missing 'type', which must be {_ACCEPTED_TYPES} — {_DROPPED}",
                file_path=block.path,
            )

        handler_type = handler["type"]
        if not isinstance(handler_type, str):
            # An unhashable ``type`` (list/dict) would raise ``TypeError`` in
            # a set membership test and cost every remaining finding.
            return self.violation(
                f"{where} 'type' must be exactly {_ACCEPTED_TYPES}, got "
                f"{safe_display(repr(handler_type))} — {_DROPPED}",
                file_path=block.path,
            )

        if handler_type in muse.HOOK_HANDLER_TYPES:
            return None

        if handler_type in _OTHER_HOST_HANDLER_TYPES:
            return self.violation(
                f"{where} has type '{safe_display(handler_type)}', but Muse runs only "
                f"command handlers — {_DROPPED}",
                file_path=block.path,
            )

        return self.violation(
            f"{where} 'type' must be exactly {_ACCEPTED_TYPES}, got "
            f"{safe_display(repr(handler_type))} — {_DROPPED}",
            file_path=block.path,
        )

    def _check_command(
        self, where: str, handler: Dict[str, Any], block: MuseHooksBlock
    ) -> List[RuleViolation]:
        """A command handler needs something to run on this platform."""
        if "command" not in handler:
            windows_only = any(key in handler for key in ("commandWindows", "command_windows"))
            if windows_only:
                # The handler loads and its Windows command runs there; on
                # every other platform it is a hook that silently does
                # nothing, which is not what the file looks like it says.
                return [
                    self.violation(
                        f"{where} sets only a Windows command — no command runs on "
                        "Linux or macOS. Add 'command' for the POSIX spelling.",
                        file_path=block.path,
                        severity=Severity.WARNING,
                    )
                ]
            return [
                self.violation(
                    f"{where} is missing 'command' — {_DROPPED}",
                    file_path=block.path,
                )
            ]

        command = handler["command"]
        # Present is not the same as runnable: ``""`` and ``[]`` both satisfy
        # a key-existence check while naming nothing to spawn.
        if not isinstance(command, str) or not command.strip():
            return [
                self.violation(
                    f"{where} 'command' must be a non-empty string — {_DROPPED}",
                    file_path=block.path,
                )
            ]
        return []

    def _check_handler_fields(
        self, where: str, handler: Dict[str, Any], block: MuseHooksBlock
    ) -> List[RuleViolation]:
        """Every other key is either typed, unsupported, or unknown."""
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            if key in _SELF_CHECKED_HANDLER_FIELDS:
                continue
            if key in muse.HANDLER_FIELDS:
                problem = self._field_type_problem(key, value)
                if problem is not None:
                    violations.append(
                        self.violation(
                            f"{where} '{key}' {problem} — {_DROPPED}",
                            file_path=block.path,
                        )
                    )
                continue
            if key in muse.UNSUPPORTED_HANDLER_FIELDS:
                violations.append(
                    self.violation(
                        f"{where} sets '{safe_display(str(key))}' — Muse rejects handlers "
                        f"that use '{safe_display(str(key))}', so it never runs",
                        file_path=block.path,
                    )
                )
                continue
            if key in muse.CLAUDE_ONLY_HANDLER_FIELDS:
                violations.append(
                    self.violation(
                        f"{where} sets '{safe_display(str(key))}' — that is a Claude Code "
                        f"field, and {_DROPPED}",
                        file_path=block.path,
                    )
                )
                continue
            violations.append(
                self.violation(
                    f"{where} has unknown field '{safe_display(str(key))}' — {_DROPPED}",
                    file_path=block.path,
                )
            )
        return violations

    def _field_type_problem(self, key: str, value: Any) -> Optional[str]:
        """How *value* fails the type Muse accepts for *key*, if it does.

        ``object``-typed entries are the fields Muse parses without a
        documented value set, so nothing here can say what a wrong one looks
        like.
        """
        expected = muse.HANDLER_FIELDS[key]
        if expected is object:
            return None
        if expected is bool:
            if isinstance(value, bool):
                return None
            return f"must be a boolean, got {type(value).__name__}"
        if expected is int:
            # ``bool`` is an ``int`` subclass, and ``timeout: true`` is not a
            # duration however permissively you read it. A float or a numeric
            # string is not one either — Muse drops the handler for both.
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return None
            return f"must be a non-negative integer, got {safe_display(repr(value))}"
        if isinstance(value, expected):
            return None
        return f"must be a {expected.__name__}, got {type(value).__name__}"
