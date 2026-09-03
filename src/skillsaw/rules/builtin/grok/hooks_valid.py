"""
Rule: grok-hooks-valid

Validates `.grok/hooks/*.json` against Grok Build's events, alias table and
handler fields. The vocabulary lives in ``skillsaw.formats.grok`` — this
rule reads it and never restates it. Severity carries the blast radius —
what each defect costs, and how to fix it, is on the rule's documentation
page.

Only :class:`GrokHooksBlock` is iterated, a node type that exists only where
Grok's project layer does, so the rule declares no ``provenance_scope``:
``.grok/`` is a tool directory no other ecosystem claims.
"""

from typing import Any, Dict, List, Optional, Set

from skillsaw.blocks import json_token
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import GrokHooksBlock
from skillsaw.rules.builtin.utils import rust_matcher_error

#: The handler types Grok runs, rendered for a message.
_ACCEPTED_TYPES = " or ".join(f"'{name}'" for name in sorted(grok.HOOK_HANDLER_TYPES))


class GrokHooksValidRule(Rule):
    """Validate the structure of a Grok Build hooks file"""

    since = "0.20.0"

    # ``enabled: auto`` on the base default, gated on the one place these
    # files live: a checkout carrying a ``.grok/`` project layer.
    repo_types = frozenset({RepositoryType.GROK_PROJECT})

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
        return "grok-hooks-valid"

    @property
    def description(self) -> str:
        return ".grok/hooks/*.json must use Grok's hook events, handler types and fields"

    def default_severity(self) -> Severity:
        # A wrong-typed field anywhere in the file costs every hook in it,
        # and Grok reports nothing: ``grok inspect --json`` returned
        # ``configWarnings: null`` for every rejected file in the matrix.
        return Severity.ERROR

    def _known_events(self) -> Set[str]:
        """Grok's events and their aliases, plus any the project declares.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would raise
        ``TypeError`` and cost every structural finding in every hooks file
        over one bad config line.
        """
        known = set(grok.HOOK_EVENTS) | set(grok.HOOK_EVENT_ALIASES)
        extra = self.setting("extra-events") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return known
        return known | {event for event in extra if isinstance(event, str)}

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        known_events = self._known_events()

        for block in context.lint_tree.find(GrokHooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
                continue

            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation(f"{block.path.name} must be a JSON object", file_path=block.path)
                )
                continue

            # Before the shape walk, and instead of it. ``GrokHooksBlock``
            # parses leniently so a duplicate key cannot hide executable
            # surface from the security rules, and Python's ``json`` throws
            # in the bare tokens ``NaN``, ``Infinity`` and ``-Infinity``
            # along the way. Grok reads the file with ``serde_json``, which
            # accepts none of them and refuses the document — so the defect
            # is the file, not the field, and one finding says so.
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

            violations.extend(_FileCheck(self, block, known_events).run(data))

        return violations


class _FileCheck:
    """One hooks file, walked once."""

    def __init__(self, rule: GrokHooksValidRule, block: GrokHooksBlock, events: Set[str]) -> None:
        self.rule = rule
        self.block = block
        self.known_events = events

    def _violation(self, message: str, severity: Optional[Severity] = None) -> RuleViolation:
        return self.rule.violation(message, file_path=self.block.path, severity=severity)

    # -- the walk -------------------------------------------------

    def run(self, data: Dict[str, Any]) -> List[RuleViolation]:
        """``hooks`` holds every event Grok dispatches on.

        Keys beside it are ignored rather than refused, so reporting one
        would be a finding with no defect.
        """
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
        """An event Grok does not dispatch loses its entries; the file loads."""
        if event in self.known_events:
            return []
        # A warning rather than an error, on two counts: the rest of the file
        # loads, and Grok ships events faster than skillsaw releases, so
        # ``extra-events`` accepts a newer one.
        return [self._violation(f"Unknown hook event '{safe_display(event)}'", Severity.WARNING)]

    def _check_groups(self, event: str, groups: Any) -> List[RuleViolation]:
        """Each event holds an array of matcher groups, or the file is refused."""
        if not isinstance(groups, list):
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' must be an array of matcher groups"
                )
            ]

        if not groups:
            return [
                self._violation(
                    f"Hook event '{safe_display(event)}' has an empty array", Severity.WARNING
                )
            ]

        violations: List[RuleViolation] = []
        for index, group in enumerate(groups):
            where = f"{safe_display(event)}[{index}]"
            if not isinstance(group, dict):
                violations.append(self._violation(f"Hook {where} must be an object"))
                continue
            violations.extend(self._check_group(where, event, group))
        return violations

    def _check_group(self, where: str, event: str, group: Dict[str, Any]) -> List[RuleViolation]:
        """A matcher group carries an optional ``matcher`` and a ``hooks`` array.

        Keys beside those two are tolerated — a ``description`` carried over
        from a Claude Code file loads unchanged — so only the two are read.
        """
        violations = self._check_matcher(where, event, group)

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

    def _check_matcher(self, where: str, event: str, group: Dict[str, Any]) -> List[RuleViolation]:
        """``matcher`` is an optional regex; a non-string one refuses the file."""
        if "matcher" not in group:
            return []

        matcher = group["matcher"]
        if not isinstance(matcher, str):
            return [
                self._violation(
                    f"Hook {where} 'matcher' must be a string, got {type(matcher).__name__}"
                )
            ]

        if matcher in grok.WILDCARD_MATCHERS:
            # "Everything", which is what an omitted matcher already means.
            # Grok never compiles either spelling, and saying a catch-all has
            # no effect on an event that always fires is a finding with no
            # defect behind it.
            return []

        if grok.normalize_event(event) in grok.MATCHER_IGNORED_EVENTS:
            # Kept in the loaded configuration and ignored at dispatch: the
            # event always fires, and Grok does not even compile the pattern,
            # so an uncompilable one here costs nothing either. Advisory,
            # because nothing is lost.
            return [
                self._violation(
                    f"Hook {where} 'matcher' has no effect on {safe_display(event)}",
                    Severity.INFO,
                )
            ]

        detail = rust_matcher_error(matcher)
        if detail is not None:
            # A warning, not an error: Grok compiles matchers with Rust's
            # regex engine, and the dialects differ at the edges.
            return [
                self._violation(
                    f"Hook {where} 'matcher' {safe_display(repr(matcher))} does not "
                    f"compile: {detail}",
                    Severity.WARNING,
                )
            ]
        return []

    def _check_handler(self, where: str, handler: Any) -> List[RuleViolation]:
        """One handler: its type, the field that type needs, and its ``env``.

        Keys Grok does not know are tolerated, so they are never reported.
        """
        if not isinstance(handler, dict):
            return [self._violation(f"Hook {where} must be an object")]

        violations = self._check_field_types(where, handler)

        if "type" not in handler:
            # ``type`` has no default: serde refuses the document without it,
            # so this costs every hook in the file.
            violations.append(self._violation(f"Hook {where} is missing 'type'"))
            return violations

        handler_type = handler["type"]
        if not isinstance(handler_type, str):
            # A known field of the wrong type, already reported above as the
            # whole-file defect it is. Nothing runnable is left to judge.
            return violations

        if handler_type not in grok.HOOK_HANDLER_TYPES:
            violations.append(
                self._violation(
                    f"Hook {where} 'type' must be {_ACCEPTED_TYPES}, got "
                    f"{safe_display(repr(handler_type))}",
                    Severity.WARNING,
                )
            )
            return violations

        required = grok.HOOK_REQUIRED_FIELDS[handler_type]
        if required not in handler:
            violations.append(
                self._violation(
                    f"Hook {where} is missing '{required}'",
                    Severity.WARNING,
                )
            )

        violations.extend(self._check_env(where, handler))
        return violations

    def _check_field_types(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """A known field carrying the wrong JSON type refuses the whole file."""
        violations: List[RuleViolation] = []
        for key, value in handler.items():
            name = str(key)
            if name not in grok.HANDLER_FIELDS:
                continue
            problem = _field_type_problem(name, value)
            if problem is not None:
                violations.append(self._violation(f"Hook {where} '{name}' {problem}"))
        return violations

    def _check_env(self, where: str, handler: Dict[str, Any]) -> List[RuleViolation]:
        """Values the hook runner overwrites whatever the file says.

        Only for an ``env`` of the right shape. A non-mapping one, or one
        holding a non-string value, refuses the whole document — so nothing
        is stripped, and the field-type check above already reported the one
        defect the handler has.
        """
        env = handler.get("env")
        if not isinstance(env, dict) or not all(isinstance(value, str) for value in env.values()):
            return []
        return [
            self._violation(
                f"Hook {where} 'env' sets reserved '{safe_display(str(key))}'",
                Severity.INFO,
            )
            for key in env
            if str(key) in grok.RESERVED_ENV_VARS
        ]


def _field_type_problem(key: str, value: Any) -> Optional[str]:
    """How *value* fails the JSON type Grok accepts for *key*, if it does."""
    expected = grok.HANDLER_FIELDS[key]
    if expected is int:
        # ``bool`` is an ``int`` subclass, and ``timeout: true`` is not a
        # duration however permissively you read it. A float, a numeric
        # string and a negative are not durations either — Grok refuses the
        # file for each. A large value is fine: ``Stop`` and
        # ``SubagentStop`` default to 600 seconds and gates run test suites.
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return None
        return f"must be a non-negative integer, got {safe_display(repr(value))}"
    if expected is dict:
        if not isinstance(value, dict):
            return f"must be an object, got {type(value).__name__}"
        for name, item in value.items():
            if not isinstance(item, str):
                return (
                    f"value for '{safe_display(str(name))}' must be a string, "
                    f"got {type(item).__name__}"
                )
        return None
    if isinstance(value, expected) and not isinstance(value, bool):
        return None
    return f"must be a {expected.__name__}, got {type(value).__name__}"
