"""
Rule: codex-hooks-valid

Codex adopted Claude Code's nested hooks shape and gave it its own
vocabulary: twelve events, two handler types it runs and two it parses and
skips, and per-handler fields of its own. The vocabulary lives in
``skillsaw.formats.codex`` — this rule reads it and never restates it.
Severity carries the blast radius — what each defect costs, and how to fix
it, is on the rule's documentation page.

Only :class:`CodexHooksBlock` is iterated: a repository's
``.codex/hooks.json``, a Codex-only plugin's ``hooks/hooks.json``, files that
plugin's manifest names in ``hooks``, and hooks written inline in a
``.codex-plugin/plugin.json``. Those blocks exist only where Codex content
does, and the rule is gated to match: ``enabled: auto`` fires on a Codex
plugin or marketplace repository, or on ``RepositoryType.CODEX_PROJECT`` —
the type a committed ``.codex/hooks.json`` raises. It declares no
``provenance_scope``: the node type already scopes it, and declaring one
would make a forced ``--type codex-plugin`` with no filesystem claim skip
the very files the rule exists to report.
"""

from typing import Any, Dict, List, Set

from skillsaw.blocks import json_token
from skillsaw.context import RepositoryContext, RepositoryType
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
    repo_types = frozenset(
        {
            RepositoryType.CODEX_PLUGIN,
            RepositoryType.CODEX_MARKETPLACE,
            RepositoryType.CODEX_PROJECT,
        }
    )

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
                        f"'{json_token(value)}' at {safe_display(path)} is not valid JSON",
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
        # Whether *Codex* dispatches this event, as opposed to the project
        # having named it under ``extra-events``. Only a built-in event has
        # a documented matcher behaviour to advise about; telling a project
        # its matcher has no effect on an event this release has never heard
        # of is a guess dressed as a finding.
        builtin = event in CODEX_HOOK_EVENTS

        if not known:
            # A warning, not an error, on two counts: Codex loads the file
            # and skips the key, and Codex ships events faster than skillsaw
            # releases. ``extra-events`` accepts a newer one.
            violations.append(
                self.violation(
                    f"Unknown hook event '{name}'",
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
                    f"Hook event '{name}' must have an array of hook configurations",
                    file_path=block.path,
                )
            )
            return violations

        for index, entry in enumerate(entries):
            violations.extend(self._check_entry(name, event, index, entry, block, builtin))
        return violations

    def _check_entry(
        self,
        name: str,
        event: Any,
        index: int,
        entry: Any,
        block: CodexHooksBlock,
        builtin: bool = True,
    ) -> List[RuleViolation]:
        """One ``{matcher?, hooks: [...]}`` entry under an event."""
        violations: List[RuleViolation] = []
        where = f"{name}[{index}]"

        if not isinstance(entry, dict):
            return [self.violation(f"Hook {where} must be an object", file_path=block.path)]

        if "matcher" in entry:
            matcher = entry["matcher"]
            if not isinstance(matcher, str):
                # The block boundary coerces a non-string matcher so nothing
                # crashes; reporting here keeps the coercion from hiding the
                # defect — Codex matches tool names against the pattern, and
                # a non-string value disables the hook without an error.
                violations.append(
                    self.violation(
                        f"Hook {where} 'matcher' must be a string, got "
                        f"{type(matcher).__name__}",
                        file_path=block.path,
                    )
                )
            elif builtin and event not in CODEX_HOOK_MATCHER_EVENTS:
                violations.append(
                    self.violation(
                        f"Hook {where}.matcher has no effect on {name}",
                        file_path=block.path,
                        severity=Severity.INFO,
                    )
                )

        if "hooks" not in entry:
            return violations + [
                self.violation(f"Hook {where} is missing 'hooks'", file_path=block.path)
            ]

        handlers = entry["hooks"]
        if not isinstance(handlers, list):
            return violations + [
                self.violation(f"Hook {where} 'hooks' must be an array", file_path=block.path)
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
            return [self.violation(f"Hook {where} must be an object", file_path=block.path)]

        if "type" not in handler:
            return [self.violation(f"Hook {where} is missing 'type'", file_path=block.path)]

        handler_type = handler["type"]
        # An unhashable ``type`` (list/dict) would raise TypeError in the set
        # membership test — a rule crash that silences hook validation for
        # every remaining block. A dict value can also carry a credentialed
        # URL into text/JSON/SARIF output, so it is redacted like every other
        # manifest value echoed into a message.
        if not isinstance(handler_type, str) or handler_type not in _KNOWN_HANDLER_TYPES:
            return [
                self.violation(
                    f"Hook {where} has invalid type '{safe_display(handler_type)}'",
                    file_path=block.path,
                )
            ]

        if handler_type in CODEX_HOOK_SKIPPED_HANDLER_TYPES:
            # Claude Code runs prompt and agent handlers; Codex parses and
            # skips them, so a shared file may carry one.
            return [
                self.violation(
                    f"Hook {where} type '{handler_type}' is not run by Codex",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]

        violations = self._check_fields(where, handler_type, handler, block)

        if handler_type == "mcp_tool" and event in CODEX_HOOK_NO_MCP_TOOL_EVENTS:
            violations.append(
                self.violation(
                    f"Hook {where} 'mcp_tool' is not allowed on {safe_display(event)}",
                    file_path=block.path,
                )
            )

        violations.extend(self._check_timeout(where, event, handler, block))
        return violations

    def _check_fields(
        self, where: str, handler_type: str, handler: Dict[str, Any], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """Required fields, this type's optional fields, and the other type's.

        Both tables are read with a default: a handler type added to
        ``CODEX_HOOK_HANDLER_TYPES`` without an entry beside it passes the
        membership test above and would otherwise ``KeyError`` here, taking
        every remaining hooks finding down with it. Nothing is known about
        such a type's fields, so nothing is reported about them.
        """
        violations: List[RuleViolation] = []

        for field in CODEX_HOOK_REQUIRED_FIELDS.get(handler_type, ()):
            if field not in handler:
                violations.append(
                    self.violation(
                        f"Hook {where} of type '{handler_type}' is missing '{field}'",
                        file_path=block.path,
                    )
                )
            elif not _matches_type(handler[field], str):
                violations.append(
                    self.violation(f"Hook {where} '{field}' must be a str", file_path=block.path)
                )

        for field in handler:
            owners = _FIELD_OWNERS.get(field)
            if owners is not None and handler_type not in owners:
                violations.append(
                    self.violation(
                        f"Hook {where} '{field}' is not a '{handler_type}' field",
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
                        f"Hook {where} '{field}' must be a {expected.__name__}",
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
                    f"Hook {where} 'timeout' must be a number, got {type(timeout).__name__}",
                    file_path=block.path,
                )
            ]
        if event in CODEX_HOOK_SHORT_TIMEOUT_EVENTS and timeout > (
            CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS
        ):
            return [
                self.violation(
                    f"Hook {where} 'timeout' is {timeout}s; the limit is "
                    f"{CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS}s",
                    file_path=block.path,
                    severity=Severity.WARNING,
                )
            ]
        return []
