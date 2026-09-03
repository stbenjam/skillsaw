"""
Rule: muse-hooks-valid

Validates `.muse/hooks.json` against Muse Code's events, matcher-group keys
and handler fields. Severity carries the blast radius — what each defect
costs, and how to fix it, is on the rule's documentation page.
"""

import re
from typing import Any, Dict, List, Optional, Set

from skillsaw.blocks import json_token
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import muse
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import MuseHooksBlock

#: Matchers Muse treats as catch-all wildcards rather than compiling as a regex.
#: Muse's documentation explicitly uses "*" as a wildcard pattern.
_WILDCARD_MATCHERS = frozenset({"", "*"})

#: Handler types supported by Muse, formatted for display.
_ACCEPTED_TYPES = ", ".join(f"'{name}'" for name in sorted(muse.HOOK_HANDLER_TYPES))

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

    repo_types = frozenset({RepositoryType.MUSE})

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
                        f"Invalid JSON: {block.parse_error}",
                        file_path=block.path,
                    )
                )
                continue

            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "hooks.json must be a JSON object",
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
                        f"'{json_token(value)}' at {safe_display(path)} is not valid JSON",
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
        """One finding per unrecognized key, naming every place it appears."""
        violations: List[RuleViolation] = []
        for key, where in sorted(self.group_keys.items()):
            violations.append(
                self._violation(
                    f"'{safe_display(key)}' is not a matcher-group field "
                    f"({self._locations(where)})"
                )
            )
        for key, where in sorted(self.handler_keys.items()):
            violations.append(
                self._violation(
                    f"'{safe_display(key)}' is not a handler field ({self._locations(where)})"
                )
            )
        return violations

    def _check_hooks(self, data: Dict[str, Any]) -> List[RuleViolation]:
        """Validate the top-level 'hooks' object containing lifecycle event mappings."""
        if "hooks" not in data:
            return [self._violation("Missing 'hooks' object")]

        hooks = data["hooks"]
        if not isinstance(hooks, dict):
            return [self._violation("'hooks' must be a JSON object")]

        if not hooks:
            return [self._violation("'hooks' is empty", Severity.WARNING)]

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
                    f"Hook event '{shown}' is not in Muse's documented event list",
                    Severity.INFO,
                )
            ]

        if event in muse.RECOGNIZED_UNRUN_EVENTS:
            return [
                self._violation(
                    f"Hook event '{shown}' is not run by Muse",
                    Severity.WARNING,
                )
            ]

        if event in self.known_events:
            return []

        # A warning rather than an error: Muse ships events faster than
        # skillsaw releases, and ``extra-events`` accepts a newer one.
        return [self._violation(f"Unknown hook event '{shown}'", Severity.WARNING)]

    def _check_groups(self, event: str, groups: Any) -> List[RuleViolation]:
        """Validate that each event maps to a list of matcher groups."""
        if not isinstance(groups, list):
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' must be an array of matcher groups"
                )
            ]

        if not groups:
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' has an empty array",
                    Severity.WARNING,
                )
            ]

        violations: List[RuleViolation] = []
        for index, group in enumerate(groups):
            where = f"{safe_display(event)}[{index}]"
            if not isinstance(group, dict):
                violations.append(self._violation(f"Hook {where} must be an object"))
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
            violations.append(self._violation(f"Hook {where} is missing 'hooks'"))
            return violations

        handlers = group["hooks"]
        if not isinstance(handlers, list):
            violations.append(self._violation(f"Hook {where} 'hooks' must be an array of handlers"))
            return violations

        if not handlers:
            violations.append(
                self._violation(f"Hook {where} has an empty 'hooks' array", Severity.WARNING)
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
                    f"Hook {where} 'matcher' must be a string, got {type(matcher).__name__}"
                )
            ]

        if matcher in _WILDCARD_MATCHERS:
            return []

        try:
            # Test regex compilation against normalized pattern syntax.
            re.compile(_to_python_regex(matcher))
        except (re.error, RecursionError, OverflowError) as err:
            # A warning, not an error: Muse compiles matchers with Rust's
            # regex engine, and the dialects differ at the edges.
            detail = getattr(err, "msg", None) or str(err)
            return [
                self._violation(
                    f"Hook {where} 'matcher' {safe_display(repr(matcher))} does not "
                    f"compile: {detail}",
                    Severity.WARNING,
                )
            ]
        return []

    def _check_handler(self, where: str, handler: Any) -> List[RuleViolation]:
        """Validate the configuration and options of an individual hook handler."""
        if not isinstance(handler, dict):
            return [self._violation(f"Hook {where} must be an object")]

        violations = self._check_field_types(where, handler)
        handler_type = handler.get("type")

        if not isinstance(handler_type, str):
            # If 'type' is missing or not a string, report if absent and stop further handler checks.
            if "type" not in handler:
                violations.append(self._violation(f"Hook {where} is missing 'type'"))
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
                violations.append(self._violation(f"Hook {where} '{name}' {problem}"))
        return violations

    def _collect_unknown_fields(self, where: str, handler: Dict[str, Any]) -> None:
        """Collect unrecognized handler field names for consolidated reporting."""
        for key in handler:
            name = str(key)
            if name not in self.known_handler_fields:
                self.handler_keys.setdefault(name, []).append(where)

    def _unknown_handler_type(self, where: str, handler_type: str) -> RuleViolation:
        """Report a handler type Muse does not run."""
        return self._violation(
            f"Hook {where} 'type' must be {_ACCEPTED_TYPES}, got "
            f"{safe_display(repr(handler_type))}"
        )

    def _check_command(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Ensure the command handler specifies a runnable command."""
        if "command" not in handler:
            windows = next(
                (key for key in ("commandWindows", "command_windows") if key in handler), None
            )
            if windows is not None:
                return [
                    self._violation(
                        f"Hook {where} has '{windows}' but no 'command'", Severity.WARNING
                    )
                ]
            return [self._violation(f"Hook {where} is missing 'command'")]

        command = handler["command"]
        # Verify that the command string contains non-whitespace content to execute.
        if isinstance(command, str) and not command.strip():
            return [self._violation(f"Hook {where} 'command' is empty")]
        return []

    def _check_unsupported_fields(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Check for handler options that are recognized by Muse but not supported during execution."""
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            if key in muse.UNSUPPORTED_HANDLER_FIELDS and isinstance(value, str):
                violations.append(self._violation(f"Hook {where} '{key}' is not supported by Muse"))
            elif key in muse.UNSUPPORTED_WHEN_TRUE and value is True:
                violations.append(self._violation(f"Hook {where} '{key}' must not be true"))
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
