"""
Rule: cursor-hooks-valid
"""

from typing import Any, Dict, List, Set

from skillsaw.context import HAS_CURSOR, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import CursorHooksBlock
from skillsaw.utils import is_finite_number

#: The only value Cursor's hooks schema accepts today.
_SUPPORTED_VERSION = 1

#: Lifecycle events Cursor dispatches hooks on, per the hooks reference as of
#: 2026-08. A name outside this set never fires — Cursor reads the file, finds
#: no matching event, and runs nothing, with no diagnostic.
#:
#: Cursor adds events faster than skillsaw releases (the 1.7 launch set was
#: six of these), so this is a floor, not a ceiling: the rule only warns, and
#: ``extra-events`` lets a project name an event newer than its skillsaw
#: without waiting for a release.
CURSOR_HOOK_EVENTS = frozenset(
    {
        # Agent session lifecycle
        "sessionStart",
        "sessionEnd",
        "stop",
        "preCompact",
        # Tool use
        "preToolUse",
        "postToolUse",
        "postToolUseFailure",
        "beforeShellExecution",
        "afterShellExecution",
        "beforeMCPExecution",
        "afterMCPExecution",
        "beforeReadFile",
        "afterFileEdit",
        # Prompt and response
        "beforeSubmitPrompt",
        "afterAgentResponse",
        "afterAgentThought",
        # Subagents
        "subagentStart",
        "subagentStop",
        # Tab (autonomous completions)
        "beforeTabFileRead",
        "afterTabFileEdit",
        # Application lifecycle, outside any agent session
        "workspaceOpen",
    }
)

#: Hook entry kinds. A command hook spawns a process; a prompt hook asks the
#: model a question and carries its text in ``prompt`` rather than ``command``.
_COMMAND_TYPE = "command"
_PROMPT_TYPE = "prompt"
_HOOK_TYPES = (_COMMAND_TYPE, _PROMPT_TYPE)


class CursorHooksValidRule(Rule):
    """Validate the structure of .cursor/hooks.json"""

    since = "0.19.0"

    formats = frozenset({HAS_CURSOR})

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
        return "cursor-hooks-valid"

    @property
    def description(self) -> str:
        return ".cursor/hooks.json must declare version 1 and known hook events with commands"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _known_events(self) -> Set[str]:
        """Built-in event names plus any the project declares.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would
        raise ``TypeError`` and cost the whole rule — every structural
        finding in every Cursor hooks file, over one bad config line. A
        value of the wrong shape simply contributes no extra events.
        """
        extra = self.config.get("extra-events") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return CURSOR_HOOK_EVENTS
        return CURSOR_HOOK_EVENTS | {e for e in extra if isinstance(e, str)}

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
        # ``True`` is an int in Python but not a version anywhere else, and
        # ``1.0`` compares equal to ``1`` while not being what the schema
        # accepts. Require the integer itself, and report with ``repr`` so
        # ``"1"`` and ``1`` do not render identically — a quoted version is
        # the same authoring mistake as a quoted ``alwaysApply``.
        if not isinstance(version, int) or isinstance(version, bool):
            return [
                self.violation(
                    f"'version' must be the number {_SUPPORTED_VERSION}, got "
                    f"{safe_display(repr(version))}",
                    file_path=block.path,
                )
            ]
        if version != _SUPPORTED_VERSION:
            return [
                self.violation(
                    f"'version' must be {_SUPPORTED_VERSION}, got {version}",
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

        known = self._known_events()
        for event, entries in hooks.items():
            if event not in known:
                # A warning, not an error, on two counts: Cursor ignores the
                # key so the file still loads, and Cursor ships new events
                # faster than skillsaw releases. ``extra-events`` is named
                # in the message so a false positive has a same-day remedy.
                violations.append(
                    self.violation(
                        f"Unknown hook event '{safe_display(str(event))}' — Cursor "
                        "dispatches no such event, so this hook never fires. If "
                        "Cursor added it after this skillsaw release, list it under "
                        "cursor-hooks-valid 'extra-events'.",
                        file_path=block.path,
                        severity=Severity.WARNING,
                    )
                )
                # Fall through rather than skipping. The warning already says
                # the name may be a real event this release has not heard of;
                # if it is, its entries are live configuration and deserve the
                # same shape checks. Skipping them would leave a malformed hook
                # invisible until the author found and set ``extra-events``.
            violations.extend(self._check_entries(event, entries, block))

        return violations

    def _check_entries(
        self, event: str, entries: Any, block: CursorHooksBlock
    ) -> List[RuleViolation]:
        """Each entry under an event must carry a non-empty command string."""
        if not isinstance(entries, list):
            return [
                self.violation(
                    f"Hook event '{safe_display(event)}' must be an array of hook objects",
                    file_path=block.path,
                )
            ]

        if not entries:
            return [
                self.violation(
                    f"Hook event '{safe_display(event)}' has an empty array — "
                    "it configures no hook",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        violations: List[RuleViolation] = []
        for index, entry in enumerate(entries):
            where = f"Hook {safe_display(event)}[{index}]"
            if not isinstance(entry, dict):
                violations.append(
                    self.violation(f"{where} must be an object", file_path=block.path)
                )
                continue
            violations.extend(self._check_entry(where, entry, block))

        return violations

    def _check_entry(
        self, where: str, entry: Dict[str, Any], block: CursorHooksBlock
    ) -> List[RuleViolation]:
        """Check one hook entry, whose required payload depends on its type."""
        # ``type`` is optional and defaults to a command hook.
        raw_type = entry.get("type", _COMMAND_TYPE)
        if raw_type not in _HOOK_TYPES:
            return [
                self.violation(
                    f"{where} has unknown 'type' {safe_display(repr(raw_type))} — "
                    f"must be one of: {', '.join(_HOOK_TYPES)}",
                    file_path=block.path,
                )
            ]

        # A prompt hook asks the model a question and carries its text in
        # ``prompt``; only a command hook names something to spawn.
        payload_key = _PROMPT_TYPE if raw_type == _PROMPT_TYPE else _COMMAND_TYPE
        if payload_key not in entry:
            return [self.violation(f"{where} is missing '{payload_key}'", file_path=block.path)]

        payload = entry[payload_key]
        # Present is not the same as runnable: ``""`` and ``[]`` both satisfy
        # a key-existence check while naming nothing to spawn.
        if not isinstance(payload, str) or not payload.strip():
            return [
                self.violation(
                    f"{where} '{payload_key}' must be a non-empty string",
                    file_path=block.path,
                )
            ]
        return self._check_optional_fields(where, entry, block)

    def _check_optional_fields(
        self, where: str, entry: Dict[str, Any], block: CursorHooksBlock
    ) -> List[RuleViolation]:
        """Check the optional fields a valid payload can still get wrong.

        A malformed ``matcher`` is the one that matters: the block coerces it
        to the ``.*`` wildcard so the security scanners still see the hook,
        which means an author who wrote a list gets a hook that fires on
        *everything* and no indication of it from anywhere else.
        """
        violations: List[RuleViolation] = []
        matcher = entry.get("matcher")
        if matcher is not None and not isinstance(matcher, str):
            violations.append(
                self.violation(
                    f"{where} 'matcher' must be a string, got "
                    f"{type(matcher).__name__} — Cursor falls back to matching everything",
                    file_path=block.path,
                )
            )
        timeout = entry.get("timeout")
        # ``bool`` is an ``int`` subclass, and ``timeout: true`` is not a
        # duration however permissively you read it.
        # The NaN/Infinity half of this is normally unreachable — the block
        # parses strictly, so such a file fails above as invalid JSON — but
        # this rule's correctness should not depend on a flag set on a class
        # in another module. A huge integer literal is finite and stays
        # accepted, without the float conversion that would kill the rule.
        if timeout is not None and not is_finite_number(timeout):
            violations.append(
                self.violation(
                    f"{where} 'timeout' must be a number, got {type(timeout).__name__}",
                    file_path=block.path,
                )
            )
        return violations
