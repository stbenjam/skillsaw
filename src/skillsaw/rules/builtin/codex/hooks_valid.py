"""
Rule: codex-hooks-valid

Codex adopted Claude Code's nested hooks shape and gave it its own
vocabulary: twelve events, two handler types it runs and two it parses and
skips, and per-handler fields of its own. The vocabulary lives in
``skillsaw.formats.codex`` — this rule reads it and never restates it.

Only :class:`CodexHooksBlock` is iterated: a repository's
``.codex/hooks.json``, a Codex-only plugin's ``hooks/hooks.json``, files that
plugin's manifest names in ``hooks``, and hooks written inline in a
``.codex-plugin/plugin.json``. Those blocks exist only where Codex content
does, and the rule is gated to match: ``enabled: auto`` fires on a Codex
plugin or marketplace repository, or on ``HAS_CODEX`` — the format label a
committed ``.codex/hooks.json`` raises. It declares no ``provenance_scope``:
the node type already scopes it, and declaring one would make a forced
``--type codex`` with no filesystem claim skip the very files the rule exists
to report.
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

#: Every handler type this rule can say something useful about: the two
#: Codex runs plus the two it parses and skips. A type outside this set is
#: a typo or another host's vocabulary.
_KNOWN_HANDLER_TYPES = CODEX_HOOK_HANDLER_TYPES | CODEX_HOOK_SKIPPED_HANDLER_TYPES

#: ``timeout`` needs a finiteness check rather than an ``isinstance``, so it
#: is handled on its own path instead of through the generic type table.
_TIMEOUT = "timeout"


def _fields_by_handler_type() -> Dict[str, frozenset]:
    """Which handler types accept each field, derived from the vocabulary.

    Inverted from the required/optional tables rather than written out, so
    a field added to ``skillsaw.formats.codex`` is placed on the right
    handler type here without a second edit.
    """
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

    # ``enabled: auto`` on the base default, gated on the two places Codex
    # hooks live: a Codex plugin or marketplace repository, and any checkout
    # that commits a ``.codex/hooks.json``. Project policy forbids a new rule
    # defaulting to ``True``.
    repo_types = CODEX_PLUGIN_REPO_TYPES
    formats = frozenset({HAS_CODEX})

    # These checks used to be reported by ``hooks-json-valid``, so a
    # baseline written before the split recorded a Codex-only plugin's
    # findings under that ID. Not an ``alias``: the rule is configured and
    # suppressed by its own name — only the baseline lookup follows this.
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
        """Codex's events plus any the project declares.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would
        raise ``TypeError`` and cost every structural finding in every
        Codex hooks file over one bad config line.
        """
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

            # Before the shape walk, and instead of it. ``CodexHooksBlock``
            # parses leniently so a duplicate key cannot hide executable
            # surface from the security rules, and Python's ``json`` throws
            # in the bare tokens ``NaN``, ``Infinity`` and ``-Infinity``
            # along the way. Codex's parser accepts none of them and refuses
            # the document — so the defect is the file, not the field, and
            # one finding says so.
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
            # Fall through rather than skipping: if the name is a real event
            # this release has not heard of, its entries are live
            # configuration and deserve the same shape checks.

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
        """One ``{matcher?, hooks: [...]}`` entry under an event."""
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
                # The block boundary coerces a non-string matcher so nothing
                # crashes; reporting here keeps the coercion from hiding the
                # defect — Codex matches tool names against the pattern, and
                # a non-string value disables the hook without an error.
                violations.append(
                    self.violation(
                        f"Event '{where}.matcher' must be a string", file_path=block.path
                    )
                )
            elif known and event not in CODEX_HOOK_MATCHER_EVENTS:
                # Only for an event Codex actually dispatches. On a typo the
                # unknown-event warning already says the entry never fires,
                # and "your matcher is ignored" on top of it is a second
                # finding for one mistake.
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
        """One handler object: its type, then the fields that type takes."""
        if not isinstance(handler, dict):
            return [self.violation(f"Event '{where}' must be an object", file_path=block.path)]

        if "type" not in handler:
            return [
                self.violation(f"Event '{where}' must have a 'type' field", file_path=block.path)
            ]

        handler_type = handler["type"]
        # An unhashable ``type`` (list/dict) would raise TypeError in the set
        # membership test — a rule crash that silences hook validation for
        # every remaining block. A dict value can also carry a credentialed
        # URL into text/JSON/SARIF output, so it is redacted like every other
        # manifest value echoed into a message.
        if not isinstance(handler_type, str) or handler_type not in _KNOWN_HANDLER_TYPES:
            return [
                self.violation(
                    f"Event '{where}' has invalid type '{safe_display(handler_type)}'. "
                    f"Valid types: {', '.join(sorted(CODEX_HOOK_HANDLER_TYPES))}",
                    file_path=block.path,
                )
            ]

        if handler_type in CODEX_HOOK_SKIPPED_HANDLER_TYPES:
            # Not an error: the file loads and the rest of it runs. Claude
            # Code runs these types, so a shared hooks file may carry one
            # deliberately — but under Codex it is dead configuration.
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
        """Required fields, this type's optional fields, and the other type's."""
        violations: List[RuleViolation] = []

        for field in CODEX_HOOK_REQUIRED_FIELDS[handler_type]:
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

        for field, expected in CODEX_HOOK_OPTIONAL_FIELDS[handler_type].items():
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
        """``timeout`` must be a finite number, and short events cap it.

        ``bool`` is an ``int`` subclass and ``timeout: true`` is not a
        duration; a huge integer literal is finite and stays accepted,
        without the float conversion that would kill the rule.
        """
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
