"""
Rule: muse-hooks-valid

Muse Code's loader says nothing in a headless run about anything it
refuses, so the only thing that distinguishes one defect from another is
how much it costs: a whole file, one matcher group, one event's entries, or
one handler. Every message here names that scope, and
:mod:`skillsaw.formats.muse` is where the scopes are recorded.
"""

import re
from typing import Any, Dict, List, Optional, Set

from skillsaw.blocks import json_token
from skillsaw.context import HAS_MUSE, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import muse
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import MuseHooksBlock

#: Matchers Muse treats as "everything" rather than compiling as a pattern.
#: ``"*"`` is not a valid regex — reporting it would be a false positive on
#: the spelling Muse's own documentation uses for a catch-all.
_WILDCARD_MATCHERS = frozenset({"", "*"})

#: The handler types other hosts define, named so the diagnostic can say why
#: Muse drops them rather than only that it does.
_OTHER_HOST_HANDLER_TYPES = frozenset({"http", "prompt", "agent", "mcp_tool"})

#: The handler types Muse runs, rendered for a message.
_ACCEPTED_TYPES = ", ".join(f"'{name}'" for name in sorted(muse.HOOK_HANDLER_TYPES))

#: The keys a matcher group may carry, rendered for a message.
_GROUP_FIELDS = " and ".join(f"'{name}'" for name in sorted(muse.MATCHER_GROUP_FIELDS))

#: The three verdicts, one per failure scope. Which one a message carries is
#: the whole point of the finding: a wrong-typed ``timeout`` costs every hook
#: in the file, while an unknown handler key costs one handler.
_WHOLE_FILE = "Muse rejects the whole file, so no hook in it runs"
_GROUP_DROPPED = "Muse drops this matcher group, so no hook in it runs"
_HANDLER_DROPPED = "Muse drops this handler, so it never runs"

#: How many group or handler locations a consolidated finding names before
#: it stops listing them. A file copied from Claude Code carries the same
#: stray key in every group, and thirty findings for one habit is noise.
_MAX_LOCATIONS = 4

#: Unicode character classes: ``\p{Greek}``, ``\pL`` and their negations.
#: Rust's ``regex`` crate compiles these and Python's ``re`` raises on them.
_RUST_UNICODE_CLASS = re.compile(r"\\[pP](?:\{[^}]*\}|[A-Za-z])")

#: Rust's character-class set operators: ``[a-z&&[^aeiou]]``,
#: ``[\w--\d]``, ``[a-g~~b-h]``. Python has no equivalent syntax.
_RUST_CLASS_SET_OPERATORS = ("&&", "--", "~~")


def _uses_rust_only_regex_syntax(pattern: str) -> bool:
    """Whether *pattern* uses regex syntax only Rust's engine has.

    Muse compiles a matcher with the Rust ``regex`` crate, whose dialect is
    not Python's: it has no look-around and no backreferences, and it adds
    two constructs a hooks file plausibly reaches — Unicode character
    classes and the character-class set operators. Python raises on both,
    so compiling such a pattern here and reporting the exception would call
    a working matcher broken. Deliberately generous — a missed defect in a
    ``warning`` costs less than a false one.
    """
    if _RUST_UNICODE_CLASS.search(pattern):
        return True
    opened = pattern.find("[")
    if opened == -1:
        return False
    return any(operator in pattern[opened:] for operator in _RUST_CLASS_SET_OPERATORS)


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
        "extra-handler-fields": {
            "type": "list",
            "default": [],
            "description": (
                "Additional handler field names to accept, for fields newer "
                "than this skillsaw release"
            ),
        },
        "extra-group-keys": {
            "type": "list",
            "default": [],
            "description": (
                "Additional matcher-group key names to accept, for keys newer "
                "than this skillsaw release"
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

    def _declared(self, option: str) -> Set[str]:
        """The string members of a list-valued config option.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would raise
        ``TypeError`` and cost every structural finding in the file over one
        bad config line; a value of the wrong shape contributes nothing.
        """
        value = self.setting(option) or []
        if not isinstance(value, (list, tuple, set, frozenset)):
            return set()
        return {item for item in value if isinstance(item, str)}

    def _known_events(self) -> Set[str]:
        """Muse's documented events, its undocumented ones, and the project's."""
        return (
            set(muse.HOOK_EVENTS)
            | set(muse.UNDOCUMENTED_HOOK_EVENTS)
            | self._declared("extra-events")
        )

    def _known_handler_fields(self) -> Set[str]:
        """Muse's handler fields plus any the project declares.

        A declared field is accepted, never type-checked: skillsaw does not
        know what Muse expects of a field it has not heard of.
        """
        return set(muse.HANDLER_FIELDS) | self._declared("extra-handler-fields")

    def _known_group_keys(self) -> Set[str]:
        """Muse's matcher-group keys plus any the project declares."""
        return set(muse.MATCHER_GROUP_FIELDS) | self._declared("extra-group-keys")

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
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "hooks.json must be a JSON object — Muse loads no hooks from this file",
                        file_path=block.path,
                    )
                )
                continue

            # Before the shape walk, and instead of it. ``MuseHooksBlock``
            # parses leniently so a duplicate key cannot hide executable
            # surface from the security rules, and Python's ``json`` throws
            # in the bare tokens ``NaN``, ``Infinity`` and ``-Infinity``
            # along the way. Muse reads the file with ``serde_json``, which
            # accepts none of them and refuses the document — so the defect
            # is the file, not the field, and one finding says so.
            found = block.first_non_finite()
            if found is not None:
                path, value = found
                violations.append(
                    self.violation(
                        f"'{json_token(value)}' at {safe_display(path)} is not valid JSON "
                        f"— NaN and Infinity are not JSON tokens, and {_WHOLE_FILE}",
                        file_path=block.path,
                    )
                )
                continue

            violations.extend(_FileCheck(self, block).run(data))

        return violations


class _FileCheck:
    """One hooks file, walked once.

    Stray keys are collected rather than reported where they are found: a
    file copied from Claude Code carries the same ``description`` in every
    matcher group, and one finding per group buries the rest of the report.
    """

    def __init__(self, rule: MuseHooksValidRule, block: MuseHooksBlock) -> None:
        self.rule = rule
        self.block = block
        self.known_events = rule._known_events()
        self.known_handler_fields = rule._known_handler_fields()
        self.known_group_keys = rule._known_group_keys()
        #: stray key -> the group locations that carry it
        self.group_keys: Dict[str, List[str]] = {}
        #: stray key -> the handler locations that carry it
        self.handler_keys: Dict[str, List[str]] = {}

    # -- helpers --------------------------------------------------

    def _violation(self, message: str, severity: Optional[Severity] = None) -> RuleViolation:
        return self.rule.violation(message, file_path=self.block.path, severity=severity)

    @staticmethod
    def _locations(where: List[str]) -> str:
        shown = ", ".join(where[:_MAX_LOCATIONS])
        return shown if len(where) <= _MAX_LOCATIONS else f"{shown}, …"

    # -- the walk -------------------------------------------------

    def run(self, data: Dict[str, Any]) -> List[RuleViolation]:
        violations = self._check_hooks(data)
        violations.extend(self._consolidated())
        return violations

    def _consolidated(self) -> List[RuleViolation]:
        """One finding per stray key, naming where it appears.

        A file copied from Claude Code carries the same key in every group
        or every handler, and the defect is the habit, not each instance.
        """
        violations: List[RuleViolation] = []
        for key, where in sorted(self.group_keys.items()):
            one = len(where) == 1
            subject = "1 matcher group carries" if one else f"{len(where)} matcher groups carry"
            verdict = (
                "Muse drops it, so no hook in it runs"
                if one
                else "Muse drops each of them, so no hook in them runs"
            )
            violations.append(
                self._violation(
                    f"{subject} '{safe_display(key)}' ({self._locations(where)}), and a "
                    f"matcher group may carry only {_GROUP_FIELDS} — {verdict}. If Muse "
                    "added this key after this skillsaw release, list it under "
                    "muse-hooks-valid 'extra-group-keys'."
                )
            )
        for key, where in sorted(self.handler_keys.items()):
            one = len(where) == 1
            subject = "1 handler sets" if one else f"{len(where)} handlers set"
            verdict = (
                "Muse drops it, so it never runs"
                if one
                else "Muse drops each of them, so none of them run"
            )
            claude = (
                " That is a Claude Code field." if key in muse.CLAUDE_ONLY_HANDLER_FIELDS else ""
            )
            violations.append(
                self._violation(
                    f"{subject} '{safe_display(key)}', which Muse does not know "
                    f"({self._locations(where)}) — {verdict}.{claude} If Muse added this "
                    "field after this skillsaw release, list it under muse-hooks-valid "
                    "'extra-handler-fields'."
                )
            )
        return violations

    def _check_hooks(self, data: Dict[str, Any]) -> List[RuleViolation]:
        """``hooks`` holds every event Muse dispatches on; other keys are ignored."""
        if "hooks" not in data:
            return [self._violation("Missing 'hooks' object — Muse loads no hooks from this file")]

        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            return [
                self._violation(
                    "'hooks' must be a JSON object — Muse loads no hooks from this file"
                )
            ]

        if not hooks:
            return [
                self._violation("'hooks' is empty — the file configures nothing", Severity.WARNING)
            ]

        violations: List[RuleViolation] = []
        for event, groups in hooks.items():
            name = str(event)
            violations.extend(self._check_event_name(name))
            violations.extend(self._check_groups(name, groups))
        return violations

    def _check_event_name(self, event: str) -> List[RuleViolation]:
        """An event Muse does not dispatch skips its entries; the file loads."""
        shown = safe_display(event)

        if event in muse.UNDOCUMENTED_HOOK_EVENTS:
            return [
                self._violation(
                    f"Hook event '{shown}' is in Muse's event set but not in its "
                    "documented list — verify the hook actually fires before relying "
                    "on it.",
                    Severity.INFO,
                )
            ]

        if event in muse.RECOGNIZED_UNRUN_EVENTS:
            return [
                self._violation(
                    f"Hook event '{shown}' is a Claude Code event Muse recognises and "
                    "deliberately does not run, so this entry never fires.",
                    Severity.WARNING,
                )
            ]

        if event in self.known_events:
            return []

        # A warning, not an error: Muse skips the entry and loads the rest of
        # the file, and its event set grows between skillsaw releases.
        # ``extra-events`` is named so a false positive has a same-day remedy.
        return [
            self._violation(
                f"Unknown hook event '{shown}' — Muse dispatches no such event, so this "
                "entry never fires. Event names are case-sensitive; if Muse added this "
                "one after this skillsaw release, list it under muse-hooks-valid "
                "'extra-events'.",
                Severity.WARNING,
            )
        ]

    def _check_groups(self, event: str, groups: Any) -> List[RuleViolation]:
        """Each event holds an array of matcher groups, or the file is rejected."""
        if not isinstance(groups, list):
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' must be an array of matcher "
                    f"groups — {_WHOLE_FILE}"
                )
            ]

        if not groups:
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' has an empty array — "
                    "it configures no hook",
                    Severity.WARNING,
                )
            ]

        violations: List[RuleViolation] = []
        for index, group in enumerate(groups):
            where = f"{safe_display(event)}[{index}]"
            if not isinstance(group, dict):
                violations.append(
                    self._violation(f"Hook {where} must be an object — {_WHOLE_FILE}")
                )
                continue
            violations.extend(self._check_group(where, group))
        return violations

    def _check_group(self, where: str, group: Dict[str, Any]) -> List[RuleViolation]:
        """A matcher group carries a ``matcher`` and a ``hooks`` array, nothing else."""
        for key in group:
            if key not in self.known_group_keys:
                self.group_keys.setdefault(str(key), []).append(where)

        violations = self._check_matcher(where, group)

        if "hooks" not in group:
            violations.append(self._violation(f"Hook {where} is missing 'hooks' — {_WHOLE_FILE}"))
            return violations

        handlers = group["hooks"]
        if not isinstance(handlers, list):
            violations.append(
                self._violation(
                    f"Hook {where} 'hooks' must be an array of handlers — {_WHOLE_FILE}"
                )
            )
            return violations

        if not handlers:
            violations.append(
                self._violation(
                    f"Hook {where} has an empty 'hooks' array — it configures no hook",
                    Severity.WARNING,
                )
            )
            return violations

        for index, handler in enumerate(handlers):
            violations.extend(self._check_handler(f"{where}.hooks[{index}]", handler))
        return violations

    def _check_matcher(self, where: str, group: Dict[str, Any]) -> List[RuleViolation]:
        """``matcher`` is an optional regex; a non-string one rejects the file."""
        if "matcher" not in group:
            return []

        matcher = group["matcher"]
        if not isinstance(matcher, str):
            return [
                self._violation(
                    f"Hook {where} 'matcher' must be a string, got "
                    f"{type(matcher).__name__} — {_WHOLE_FILE}"
                )
            ]

        if matcher in _WILDCARD_MATCHERS or _uses_rust_only_regex_syntax(matcher):
            return []

        try:
            re.compile(matcher)
        except (re.error, RecursionError, OverflowError) as err:
            # A warning, not an error: Python's dialect is not Rust's, and a
            # rule that crashed here would cost every other finding in the
            # file — a deeply nested pattern raises RecursionError rather
            # than re.error.
            detail = getattr(err, "msg", None) or str(err)
            return [
                self._violation(
                    f"Hook {where} 'matcher' {safe_display(repr(matcher))} does not compile "
                    f"as a regex — {detail}. Muse compiles matchers with Rust's regex "
                    f"engine, and {_GROUP_DROPPED}.",
                    Severity.WARNING,
                )
            ]
        return []

    def _check_handler(self, where: str, handler: Any) -> List[RuleViolation]:
        """One handler: its type, something to run, and the fields Muse knows."""
        if not isinstance(handler, dict):
            return [self._violation(f"Hook {where} must be an object — {_WHOLE_FILE}")]

        violations = self._check_field_types(where, handler)
        handler_type = handler.get("type")

        if not isinstance(handler_type, str):
            # Absent, or present with a wrong-typed value the field check
            # above already reported as a whole-file problem. Either way
            # there is no runnable handler left to say anything more about.
            if "type" not in handler:
                violations.append(
                    self._violation(
                        f"Hook {where} is missing 'type', which must be {_ACCEPTED_TYPES} — "
                        f"{_HANDLER_DROPPED}"
                    )
                )
            return violations

        if handler_type not in muse.HOOK_HANDLER_TYPES:
            # Dropped on its type; reporting what it does or does not run as
            # well is several findings for one dead handler — and another
            # host's handler carries that host's fields, which are not
            # "unknown keys" so much as evidence of the type problem.
            violations.append(self._unknown_handler_type(where, handler_type))
            return violations

        self._collect_unknown_fields(where, handler)
        violations.extend(self._check_command(where, handler))
        violations.extend(self._check_unsupported_fields(where, handler))
        return violations

    def _check_field_types(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """A known field carrying the wrong JSON type rejects the whole file.

        Runs whatever the handler's ``type`` says: the file is refused at
        parse time, before anything decides which handlers to keep.
        """
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            name = str(key)
            if name not in muse.HANDLER_FIELDS:
                # Unknown, or declared through ``extra-handler-fields`` — in
                # which case it is accepted and skillsaw has no idea what
                # type Muse wants for it.
                continue
            problem = _field_type_problem(name, value)
            if problem is not None:
                violations.append(
                    self._violation(f"Hook {where} '{name}' {problem} — {_WHOLE_FILE}")
                )
        return violations

    def _collect_unknown_fields(self, where: str, handler: Dict[str, Any]) -> None:
        """Note keys Muse does not know, for one consolidated finding."""
        for key in handler:
            name = str(key)
            if name not in self.known_handler_fields:
                self.handler_keys.setdefault(name, []).append(where)

    def _unknown_handler_type(self, where: str, handler_type: str) -> RuleViolation:
        """Muse runs exactly one kind of handler; every other name is dead."""
        if handler_type in _OTHER_HOST_HANDLER_TYPES:
            return self._violation(
                f"Hook {where} has type '{safe_display(handler_type)}', but Muse runs only "
                f"command handlers — {_HANDLER_DROPPED}"
            )

        return self._violation(
            f"Hook {where} 'type' must be exactly {_ACCEPTED_TYPES}, got "
            f"{safe_display(repr(handler_type))} — {_HANDLER_DROPPED}"
        )

    def _check_command(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """A command handler needs something to run on this platform."""
        if "command" not in handler:
            if any(key in handler for key in ("commandWindows", "command_windows")):
                # The handler loads and its Windows command runs there; on
                # every other platform it is a hook that silently does
                # nothing, which is not what the file looks like it says.
                return [
                    self._violation(
                        f"Hook {where} sets only a Windows command — no command runs on "
                        "Linux or macOS. Add 'command' for the POSIX spelling.",
                        Severity.WARNING,
                    )
                ]
            return [self._violation(f"Hook {where} is missing 'command' — {_HANDLER_DROPPED}")]

        command = handler["command"]
        # A non-string ``command`` rejects the file and the field-type check
        # already said so. Present is still not the same as runnable: ``""``
        # and ``"  "`` both satisfy a key-existence check while naming
        # nothing to spawn, and those cost only the handler.
        if isinstance(command, str) and not command.strip():
            return [
                self._violation(
                    f"Hook {where} 'command' is empty — {_HANDLER_DROPPED}",
                )
            ]
        return []

    def _check_unsupported_fields(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Fields Muse parses and then refuses the handler for."""
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            if key in muse.UNSUPPORTED_HANDLER_FIELDS and isinstance(value, str):
                violations.append(
                    self._violation(
                        f"Hook {where} sets '{key}', which Muse parses and then refuses — "
                        f"{_HANDLER_DROPPED}"
                    )
                )
            elif key in muse.UNSUPPORTED_WHEN_TRUE and value is True:
                violations.append(
                    self._violation(
                        f"Hook {where} sets '{key}: true', which Muse does not support — "
                        f"{_HANDLER_DROPPED}. Remove it or set it to false."
                    )
                )
        return violations


def _field_type_problem(key: str, value: Any) -> Optional[str]:
    """How *value* fails the JSON type Muse accepts for *key*, if it does.

    ``object``-typed entries are the fields Muse parses without a documented
    value set, so nothing here can say what a wrong one looks like.
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
        # string is not one either — Muse rejects the file for both.
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return None
        return f"must be a non-negative integer, got {safe_display(repr(value))}"
    if isinstance(value, expected):
        return None
    return f"must be a {expected.__name__}, got {type(value).__name__}"
