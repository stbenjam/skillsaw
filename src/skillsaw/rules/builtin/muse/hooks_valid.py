"""
Rule: muse-hooks-valid

Validates `.muse/hooks.json` to ensure hooks run smoothly during Muse Code
sessions. Because Muse executes hooks quietly during headless workflows,
findings pinpoint the exact scope affected — whether an issue prevents the
whole file, a matcher group, an event's entries, or a single handler from running.
"""

import re
from typing import Any, Dict, List, Optional, Set

from skillsaw.blocks import json_token
from skillsaw.context import HAS_MUSE, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import muse
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import MuseHooksBlock

#: Matchers Muse treats as catch-all wildcards rather than compiling as a regex.
#: Muse's documentation explicitly uses "*" as a wildcard pattern.
_WILDCARD_MATCHERS = frozenset({"", "*"})

#: Handler types defined by other hosts, referenced to provide helpful diagnostics
#: when migrating configurations across tools.
_OTHER_HOST_HANDLER_TYPES = frozenset({"http", "prompt", "agent", "mcp_tool"})

#: Handler types supported by Muse, formatted for display.
_ACCEPTED_TYPES = ", ".join(f"'{name}'" for name in sorted(muse.HOOK_HANDLER_TYPES))

#: Allowed matcher group keys, formatted for display.
_GROUP_FIELDS = " and ".join(f"'{name}'" for name in sorted(muse.MATCHER_GROUP_FIELDS))

#: Descriptive summaries explaining the impact of each failure scope.
_WHOLE_FILE = "Muse rejects the whole file, so no hook in it runs"
_GROUP_DROPPED = "Muse drops this matcher group, so no hook in it runs"
_HANDLER_DROPPED = "Muse drops this handler, so it never runs"

#: Maximum number of specific locations to show in a consolidated finding
#: to keep diagnostic output focused and readable.
_MAX_LOCATIONS = 4

#: Unicode character classes: ``\p{Greek}``, ``\pL`` and their negations.
#: Rust's ``regex`` crate compiles these and Python's ``re`` raises on them.
_RUST_UNICODE_CLASS = re.compile(r"\\[pP](?:\{[^}]*\}|[A-Za-z])")

#: Rust's character-class set operators: ``[a-z&&[^aeiou]]``,
#: ``[\w--\d]``, ``[a-g~~b-h]``. Python has no equivalent syntax.
_RUST_CLASS_SET_OPERATOR = re.compile(r"&&|--|~~")


def _to_python_regex(pattern: str) -> str:
    """Rewrite Rust-specific regex constructs into Python-compatible forms.

    Muse compiles matchers using the Rust ``regex`` crate. While Python's
    ``re`` module supports standard regex syntax, Rust also permits Unicode
    classes (such as ``\\p{Greek}`` or ``\\pL``) and class set operators
    (``&&``, ``--``, ``~~``) that would otherwise cause Python's regex parser
    to raise a syntax error.

    To validate structural regex correctness without raising false positives
    on supported Rust patterns, this helper normalizes Rust-specific tokens
    into standard equivalents before testing pattern syntax.
    """
    substituted = _RUST_UNICODE_CLASS.sub(r"\\w", pattern)
    if "[" not in substituted:
        return substituted

    # The set operators only mean anything inside a character class: ``a--b``
    # outside one is three literal characters in either dialect. Escapes are
    # consumed whole so a ``\[`` does not open a class.
    out: List[str] = []
    depth = 0
    index = 0
    end = len(substituted)
    while index < end:
        char = substituted[index]
        if char == "\\":
            out.append(substituted[index : index + 2])
            index += 2
            continue
        if depth:
            operator = _RUST_CLASS_SET_OPERATOR.match(substituted, index)
            if operator is not None:
                index = operator.end()
                continue
        if char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        out.append(char)
        index += 1
    return "".join(out)


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
        # Hooks that fail to load are skipped without warnings in headless runs,
        # so default to ERROR to prevent silent automation failures.
        return Severity.ERROR

    def _declared(self, option: str) -> Set[str]:
        """Safely extract string values from a list-valued configuration option."""
        value = self.setting(option) or []
        if not isinstance(value, (list, tuple, set, frozenset)):
            return set()
        return {item for item in value if isinstance(item, str)}

    def _known_events(self) -> Set[str]:
        """Return recognized lifecycle events, including built-in and user-configured events."""
        return (
            set(muse.HOOK_EVENTS)
            | set(muse.UNDOCUMENTED_HOOK_EVENTS)
            | self._declared("extra-events")
        )

    def _known_handler_fields(self) -> Set[str]:
        """Return recognized handler fields, including built-in and user-configured fields."""
        return set(muse.HANDLER_FIELDS) | self._declared("extra-handler-fields")

    def _known_group_keys(self) -> Set[str]:
        """Return recognized matcher group keys, including built-in and user-configured keys."""
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

            # Verify standard JSON numeric tokens. Non-standard values like
            # NaN or Infinity cause serde_json to reject the file at parse time.
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
    """Validates a single hooks file.

    Unrecognized keys are consolidated to keep diagnostic reports focused
    and avoid repetitive messages across multiple groups or handlers.
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
        """Consolidate findings for unrecognized keys across matcher groups and handlers to provide a clean report."""
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
        """Validate the top-level 'hooks' object containing lifecycle event mappings."""
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
        """Verify that the lifecycle event name is recognized and supported by Muse Code."""
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

        # Issue a warning when an event is unrecognized so developers are alerted
        # while still allowing newer events via 'extra-events'.
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
        """Validate that each event maps to a list of matcher groups."""
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
        """Validate the structure of a single matcher group."""
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
        """Validate that the 'matcher' pattern is a valid regular expression."""
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

        if matcher in _WILDCARD_MATCHERS:
            return []

        try:
            # Test regex compilation against normalized pattern syntax.
            re.compile(_to_python_regex(matcher))
        except (re.error, RecursionError, OverflowError) as err:
            # Report regex compilation errors as warnings with clear diagnostics.
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
        """Validate the configuration and options of an individual hook handler."""
        if not isinstance(handler, dict):
            return [self._violation(f"Hook {where} must be an object — {_WHOLE_FILE}")]

        violations = self._check_field_types(where, handler)
        handler_type = handler.get("type")

        if not isinstance(handler_type, str):
            # If 'type' is missing or not a string, report if absent and stop further handler checks.
            if "type" not in handler:
                violations.append(
                    self._violation(
                        f"Hook {where} is missing 'type', which must be {_ACCEPTED_TYPES} — "
                        f"{_HANDLER_DROPPED}"
                    )
                )
            return violations

        if handler_type not in muse.HOOK_HANDLER_TYPES:
            # If the handler type is unsupported by Muse, report it directly without cascading errors for child fields.
            violations.append(self._unknown_handler_type(where, handler_type))
            return violations

        self._collect_unknown_fields(where, handler)
        violations.extend(self._check_command(where, handler))
        violations.extend(self._check_unsupported_fields(where, handler))
        return violations

    def _check_field_types(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Validate that recognized handler fields match their expected JSON data types."""
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            name = str(key)
            if name not in muse.HANDLER_FIELDS:
                # Custom or undeclared fields are skipped for strict type checking.
                continue
            problem = _field_type_problem(name, value)
            if problem is not None:
                violations.append(
                    self._violation(f"Hook {where} '{name}' {problem} — {_WHOLE_FILE}")
                )
        return violations

    def _collect_unknown_fields(self, where: str, handler: Dict[str, Any]) -> None:
        """Collect unrecognized handler field names for consolidated reporting."""
        for key in handler:
            name = str(key)
            if name not in self.known_handler_fields:
                self.handler_keys.setdefault(name, []).append(where)

    def _unknown_handler_type(self, where: str, handler_type: str) -> RuleViolation:
        """Report an unsupported handler type with clear guidance."""
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
        """Ensure the command handler specifies a runnable command."""
        if "command" not in handler:
            if any(key in handler for key in ("commandWindows", "command_windows")):
                # If only a Windows command is configured, suggest adding a POSIX command so the hook functions across platforms.
                return [
                    self._violation(
                        f"Hook {where} sets only a Windows command — no command runs on "
                        "Linux or macOS. Add 'command' for the POSIX spelling.",
                        Severity.WARNING,
                    )
                ]
            return [self._violation(f"Hook {where} is missing 'command' — {_HANDLER_DROPPED}")]

        command = handler["command"]
        # Verify that the command string contains non-whitespace content to execute.
        if isinstance(command, str) and not command.strip():
            return [
                self._violation(
                    f"Hook {where} 'command' is empty — {_HANDLER_DROPPED}",
                )
            ]
        return []

    def _check_unsupported_fields(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Check for handler options that are recognized by Muse but not supported during execution."""
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
    """Check if a field value matches the expected JSON type for the given key."""
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
