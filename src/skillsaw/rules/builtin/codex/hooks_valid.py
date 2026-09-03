"""
Rule: codex-hooks-valid

Validates Codex hooks configuration files (such as `.codex/hooks.json` or
manifest hook declarations) against Codex's supported lifecycle events,
handler types, and fields. Configuration constants are centralized in
`skillsaw.formats.codex` to keep validation rules consistent and maintainable.
"""

from typing import Any, Dict, List, Set

from skillsaw.blocks import json_token
from skillsaw.context import HAS_CODEX, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats.codex import (
    CODEX_HOOK_EVENTS,
    CODEX_HOOK_HANDLER_TYPES,
    CODEX_HOOK_MATCHER_EVENTS,
    CODEX_HOOK_NO_MCP_TOOL_EVENTS,
    CODEX_HOOK_OPTIONAL_FIELDS,
    CODEX_HOOK_REQUIRED_FIELDS,
    CODEX_HOOK_SHORT_TIMEOUT_EVENTS,
    CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS,
    CODEX_HOOK_SKIPPED_HANDLER_TYPES,
)
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.codex._helpers import CODEX_PLUGIN_REPO_TYPES
from skillsaw.rules.builtin.content_analysis import CodexHooksBlock
from skillsaw.utils import is_finite_number

#: Every handler type this rule evaluates: both actively executed types
#: and parsed types.
_KNOWN_HANDLER_TYPES = CODEX_HOOK_HANDLER_TYPES | CODEX_HOOK_SKIPPED_HANDLER_TYPES

#: Field name for timeout configurations.
_TIMEOUT = "timeout"


def _fields_by_handler_type() -> Dict[str, frozenset]:
    """Map handler fields to the handler types that support them."""
    owners: Dict[str, Set[str]] = {}
    for handler_type, fields in CODEX_HOOK_REQUIRED_FIELDS.items():
        for field in fields:
            owners.setdefault(field, set()).add(handler_type)
    for handler_type, fields in CODEX_HOOK_OPTIONAL_FIELDS.items():
        for field in fields:
            owners.setdefault(field, set()).add(handler_type)
    return {field: frozenset(types) for field, types in owners.items()}


_FIELD_OWNERS = _fields_by_handler_type()


def _matches_type(value: Any, expected) -> bool:
    """Type check that keeps ``bool`` distinct from ``int``."""
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected) and not isinstance(value, bool)


class CodexHooksValidRule(Rule):
    """Validate the structure of a Codex hooks file"""

    since = "0.20.0"

    # Auto-enable when Codex configurations are present: within Codex plugins,
    # marketplace repositories, or checkouts with `.codex/hooks.json`.
    repo_types = CODEX_PLUGIN_REPO_TYPES
    formats = frozenset({HAS_CODEX})

    # Backward-compatible alias for baselines written before codex-hooks-valid
    # was split from hooks-json-valid.
    baseline_aliases = ("hooks-json-valid",)

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
        return "codex-hooks-valid"

    @property
    def description(self) -> str:
        return "Codex hooks files must use Codex's hook events, handler types, and fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _known_events(self) -> Set[str]:
        """Return recognized hook events, including built-in and user-configured events."""
        extra = self.setting("extra-events") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return set(CODEX_HOOK_EVENTS)
        return set(CODEX_HOOK_EVENTS) | {e for e in extra if isinstance(e, str)}

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        known_events = self._known_events()

        for block in context.lint_tree.find(CodexHooksBlock):
            if block.parse_error:
                violations.append(
                    self.violation(f"Invalid JSON: {block.parse_error}", file_path=block.path)
                )
                continue

            data = block.raw_data
            if not isinstance(data, dict):
                violations.append(
                    self.violation("hooks.json must be a JSON object", file_path=block.path)
                )
                continue

            # Check for non-finite numeric tokens like NaN or Infinity, which are
            # rejected by standard JSON parsers.
            found = block.first_non_finite()
            if found is not None:
                path, value = found
                violations.append(
                    self.violation(
                        f"'{json_token(value)}' at {safe_display(path)} is not valid JSON "
                        "— NaN and Infinity are not JSON tokens, and Codex rejects the "
                        "whole file, so it loads no hooks",
                        file_path=block.path,
                    )
                )
                continue

            if "hooks" not in data:
                violations.append(
                    self.violation("hooks.json must contain a 'hooks' key", file_path=block.path)
                )
                continue

            raw_hooks = data["hooks"]
            if not isinstance(raw_hooks, dict):
                violations.append(
                    self.violation("'hooks' must be a JSON object", file_path=block.path)
                )
                continue

            for event, entries in raw_hooks.items():
                violations.extend(self._check_event(event, entries, known_events, block))

        return violations

    def _check_event(
        self, event: Any, entries: Any, known_events: Set[str], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """One event key and the entries under it."""
        violations: List[RuleViolation] = []
        name = safe_display(event)
        known = event in known_events

        if not known:
            # A warning, not an error, on two counts: Codex loads the file
            # and skips the key, and Codex ships events faster than skillsaw
            # releases. ``extra-events`` is named so a false positive has a
            # same-day remedy.
            violations.append(
                self.violation(
                    f"Unknown hook event '{name}' — Codex dispatches no such event, so "
                    "these hooks never run. If Codex added it after this skillsaw "
                    "release, list it under codex-hooks-valid 'extra-events'.",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            )
            # Continue checking entries so valid handlers under newer events
            # receive helpful shape and type validation.

        if not isinstance(entries, list):
            violations.append(
                self.violation(
                    f"Event '{name}' must have an array of hook configurations",
                    file_path=block.path,
                )
            )
            return violations

        for index, entry in enumerate(entries):
            violations.extend(self._check_entry(name, event, index, entry, block, known))
        return violations

    def _check_entry(
        self,
        name: str,
        event: Any,
        index: int,
        entry: Any,
        block: CodexHooksBlock,
        known: bool = True,
    ) -> List[RuleViolation]:
        """Validate an individual {matcher?, hooks: [...]} event entry."""
        violations: List[RuleViolation] = []
        where = f"{name}[{index}]"

        if not isinstance(entry, dict):
            return [
                self.violation(
                    f"Event '{where}' configuration must be an object", file_path=block.path
                )
            ]

        if "matcher" in entry:
            matcher = entry["matcher"]
            if not isinstance(matcher, str):
                # Non-string matchers are flagged so hooks filter as expected.
                violations.append(
                    self.violation(
                        f"Event '{where}.matcher' must be a string", file_path=block.path
                    )
                )
            elif known and event not in CODEX_HOOK_MATCHER_EVENTS:
                # Provide an advisory note if a matcher is configured on an event
                # that does not evaluate matchers.
                violations.append(
                    self.violation(
                        f"Event '{where}.matcher' is ignored on this event — Codex "
                        "filters on 'matcher' only for: "
                        f"{', '.join(sorted(CODEX_HOOK_MATCHER_EVENTS))}",
                        file_path=block.path,
                        severity=Severity.INFO,
                    )
                )

        if "hooks" not in entry:
            return violations + [
                self.violation(f"Event '{where}' must have a 'hooks' array", file_path=block.path)
            ]

        handlers = entry["hooks"]
        if not isinstance(handlers, list):
            return violations + [
                self.violation(f"Event '{where}.hooks' must be an array", file_path=block.path)
            ]

        for handler_index, handler in enumerate(handlers):
            violations.extend(
                self._check_handler(f"{where}.hooks[{handler_index}]", event, handler, block)
            )
        return violations

    def _check_handler(
        self, where: str, event: Any, handler: Any, block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """Validate the structure and options of an individual hook handler."""
        if not isinstance(handler, dict):
            return [self.violation(f"Event '{where}' must be an object", file_path=block.path)]

        if "type" not in handler:
            return [
                self.violation(f"Event '{where}' must have a 'type' field", file_path=block.path)
            ]

        handler_type = handler["type"]
        # Ensure the handler type is a string before checking membership.
        if not isinstance(handler_type, str) or handler_type not in _KNOWN_HANDLER_TYPES:
            return [
                self.violation(
                    f"Event '{where}' has invalid type '{safe_display(handler_type)}'. "
                    f"Valid types: {', '.join(sorted(CODEX_HOOK_HANDLER_TYPES))}",
                    file_path=block.path,
                )
            ]

        if handler_type in CODEX_HOOK_SKIPPED_HANDLER_TYPES:
            # Claude Code supports prompt and agent handlers, but Codex parses
            # and skips them. Provide a clear warning for shared configurations.
            return [
                self.violation(
                    f"Event '{where}' has type '{handler_type}' — Codex parses this "
                    "handler and never runs it. Codex runs only: "
                    f"{', '.join(sorted(CODEX_HOOK_HANDLER_TYPES))}",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        violations = self._check_fields(where, handler_type, handler, block)

        if handler_type == "mcp_tool" and event in CODEX_HOOK_NO_MCP_TOOL_EVENTS:
            violations.append(
                self.violation(
                    f"Event '{where}' is an 'mcp_tool' handler — {safe_display(event)} "
                    "does not support MCP tool hooks",
                    file_path=block.path,
                )
            )

        violations.extend(self._check_timeout(where, event, handler, block))
        return violations

    def _check_fields(
        self, where: str, handler_type: str, handler: Dict[str, Any], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """Validate required fields, allowed optional fields, and type correctness."""
        violations: List[RuleViolation] = []

        for field in CODEX_HOOK_REQUIRED_FIELDS.get(handler_type, ()):
            if field not in handler:
                violations.append(
                    self.violation(
                        f"Event '{where}' of type '{handler_type}' requires a " f"'{field}' field",
                        file_path=block.path,
                    )
                )
            elif not _matches_type(handler[field], str):
                violations.append(
                    self.violation(
                        f"Event '{where}' field '{field}' must be a str", file_path=block.path
                    )
                )

        for field in handler:
            owners = _FIELD_OWNERS.get(field)
            if owners is not None and handler_type not in owners:
                violations.append(
                    self.violation(
                        f"Event '{where}' field '{field}' is only valid on types: "
                        f"{', '.join(sorted(owners))}",
                        file_path=block.path,
                        severity=Severity.WARNING,
                    )
                )

        for field, expected in CODEX_HOOK_OPTIONAL_FIELDS.get(handler_type, {}).items():
            if field == _TIMEOUT or field not in handler:
                continue
            if not _matches_type(handler[field], expected):
                violations.append(
                    self.violation(
                        f"Event '{where}' field '{field}' must be a {expected.__name__}",
                        file_path=block.path,
                    )
                )

        return violations

    def _check_timeout(
        self, where: str, event: Any, handler: Dict[str, Any], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """Validate timeout settings and ensure short-timeout events stay within limits."""
        if _TIMEOUT not in handler:
            return []
        timeout = handler[_TIMEOUT]
        if not is_finite_number(timeout):
            return [
                self.violation(
                    f"Event '{where}' field 'timeout' must be a number, got "
                    f"{type(timeout).__name__}",
                    file_path=block.path,
                )
            ]
        if event in CODEX_HOOK_SHORT_TIMEOUT_EVENTS and timeout > (
            CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS
        ):
            return [
                self.violation(
                    f"Event '{where}' field 'timeout' is {timeout}s, but Codex caps "
                    f"{safe_display(event)} hooks at "
                    f"{CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS}s",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]
        return []
