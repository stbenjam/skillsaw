"""
Rule: codex-hooks-valid

Codex adopted Claude Code's nested hooks shape and gave it its own
vocabulary: twelve events, two handler types it runs and two it parses and
skips, and per-handler fields of its own. The vocabulary lives in
``skillsaw.formats.codex`` — this rule reads it and never restates it.
Severity carries the blast radius — what each defect costs, and how to fix
it, is on the rule's documentation page.

Only :class:`CodexHooksBlock` is iterated: a repository's
``.codex/hooks.json``, the ``[hooks]`` tables of its ``.codex/config.toml``,
a Codex-only plugin's ``hooks/hooks.json``, files that
plugin's manifest names in ``hooks``, and hooks written inline in a
``.codex-plugin/plugin.json``. Those blocks exist only where Codex content
does, and the rule is gated to match: ``enabled: auto`` fires on a Codex
plugin or marketplace repository, or on ``RepositoryType.CODEX_PROJECT`` —
the type either committed project-layer file raises. It declares no
``provenance_scope``: the node type already scopes it, and declaring one
would make a forced ``--type codex-plugin`` with no filesystem claim skip
the very files the rule exists to report.
"""

from pathlib import Path
from typing import AbstractSet, Any, Dict, List, Optional, Set, Tuple

from skillsaw.blocks import json_token
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.codex import (
    CODEX_HOOK_EVENTS,
    CODEX_HOOKS_FILENAME,
    CODEX_HOOK_FIELD_ALIASES,
    CODEX_HOOK_HANDLER_TYPES,
    CODEX_HOOK_MATCHER_EVENTS,
    CODEX_HOOK_NO_MCP_TOOL_EVENTS,
    CODEX_HOOK_OPTIONAL_FIELDS,
    CODEX_HOOK_REQUIRED_FIELDS,
    CODEX_HOOK_SHORT_TIMEOUT_EVENTS,
    CODEX_HOOK_SHORT_TIMEOUT_MAX_SECONDS,
    CODEX_HOOK_SKIPPED_HANDLER_TYPES,
)
from skillsaw.paths import safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import CodexConfigHooksBlock, CodexHooksBlock
from skillsaw.utils import is_finite_number

#: Every handler type this rule can say something useful about: the two
#: Codex runs plus the two it parses and skips. A type outside this set is
#: a typo or another host's vocabulary.
_KNOWN_HANDLER_TYPES = CODEX_HOOK_HANDLER_TYPES | CODEX_HOOK_SKIPPED_HANDLER_TYPES

#: ``timeout`` needs a finiteness check rather than an ``isinstance``, so it
#: is handled on its own path instead of through the generic type table.
_TIMEOUT = "timeout"

#: The handler discriminator. In neither field table — it selects which table
#: applies — so the unknown-key scan accepts it by name, on a handler only.
_TYPE = "type"

#: The keys an event-group table takes: ``{matcher?, hooks: [...]}``.
_ENTRY_FIELDS = frozenset({"matcher", "hooks"})


def _fields_by_handler_type() -> Dict[str, frozenset]:
    """Which handler types accept each field, derived from the vocabulary.

    Inverted from the required/optional tables rather than written out, so
    a field added to ``skillsaw.formats.codex`` is placed on the right
    handler type here without a second edit. Every alias Codex accepts is
    entered beside the field it renames, so a handler writing either
    spelling resolves to the same owner.
    """
    owners: Dict[str, Set[str]] = {}
    for handler_type, fields in CODEX_HOOK_REQUIRED_FIELDS.items():
        for field in fields:
            owners.setdefault(field, set()).add(handler_type)
    for handler_type, fields in CODEX_HOOK_OPTIONAL_FIELDS.items():
        for field in fields:
            owners.setdefault(field, set()).add(handler_type)
    for alias, field in CODEX_HOOK_FIELD_ALIASES.items():
        if field in owners:
            owners.setdefault(alias, set()).update(owners[field])
    return {field: frozenset(types) for field, types in owners.items()}


_FIELD_OWNERS = _fields_by_handler_type()

#: Every key a handler table may carry: any type's fields, plus the
#: discriminator that chose the type. A key outside it is one no handler
#: reads at all, as opposed to one read by the other type.
_HANDLER_KEYS = frozenset(_FIELD_OWNERS) | {_TYPE}


def _declared_fields() -> Dict[str, frozenset]:
    """Every field name each handler type takes, aliases included.

    Precomputed rather than rebuilt per handler: both source tables are
    module-level and frozen, so the union is the same on every call.
    """
    declared: Dict[str, frozenset] = {}
    for handler_type in set(CODEX_HOOK_REQUIRED_FIELDS) | set(CODEX_HOOK_OPTIONAL_FIELDS):
        fields = set(CODEX_HOOK_REQUIRED_FIELDS.get(handler_type, ())) | set(
            CODEX_HOOK_OPTIONAL_FIELDS.get(handler_type, {})
        )
        fields |= {a for a, f in CODEX_HOOK_FIELD_ALIASES.items() if f in fields}
        declared[handler_type] = frozenset(fields)
    return declared


_DECLARED_FIELDS = _declared_fields()


def _field_spellings() -> Dict[str, Tuple[str, ...]]:
    """Every spelling of each field Codex accepts more than one name for.

    Keyed by the canonical name and starting with it, so a message names the
    field before its alias. Precomputed for the same reason
    :data:`_DECLARED_FIELDS` is: the alias table is module-level and frozen.
    """
    spellings: Dict[str, List[str]] = {}
    for alias, field in CODEX_HOOK_FIELD_ALIASES.items():
        spellings.setdefault(field, [field]).append(alias)
    return {field: tuple(names) for field, names in spellings.items()}


_FIELD_SPELLINGS = _field_spellings()

#: How many names a consolidated finding shows before it counts the rest.
_SAMPLE_LIMIT = 3


def _sample(names: List[str]) -> str:
    """*names* rendered for a message, bounded with a count.

    Sliced before it is rendered: ``safe_display`` walks each string, and a
    crafted file can carry thousands of keys.
    """
    shown = ", ".join(f"'{safe_display(name)}'" for name in names[:_SAMPLE_LIMIT])
    remaining = len(names) - _SAMPLE_LIMIT
    if remaining > 0:
        shown += f", and {remaining} more"
    return shown


def _with_article(noun: str) -> str:
    """*noun* with the article the message needs.

    The blocks declare bare nouns — ``object``, ``table``, ``array of
    tables`` — because the article follows the word, not the syntax.
    """
    return f"an {noun}" if noun[:1] in "aeiou" else f"a {noun}"


def _declares_hooks(block: CodexHooksBlock) -> bool:
    """Whether *block* declares an event group Codex would merge.

    The one test for both files, so the both-files finding is made only
    where there is something to merge: a document that did not parse, or
    whose ``hooks`` mapping is absent or empty, declares nothing.
    """
    if block.parse_error is not None:
        return False
    data = block.raw_data
    events = data.get("hooks") if isinstance(data, dict) else None
    return isinstance(events, dict) and bool(events)


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
    # that commits a ``.codex/`` project layer. Project policy forbids a new
    # rule defaulting to ``True``.
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
        "extra-fields": {
            "type": "list",
            "default": [],
            "description": (
                "Additional hook handler field names to accept, for fields newer "
                "than this skillsaw release"
            ),
        },
        "allow-both-files": {
            "type": "bool",
            "default": False,
            "description": (
                "Accept a .codex/ directory that declares hooks in both "
                "hooks.json and config.toml"
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

    def _extra_fields(self) -> Set[str]:
        """Handler field names the project accepts on top of Codex's.

        Codex's handler vocabulary grows between skillsaw releases the way
        its event list does, so the unknown-field warning gets the same
        release valve ``extra-events`` gives the unknown-event one. Typed
        defensively for the same reason: the declared type is not enforced
        when the config loads.
        """
        extra = self.setting("extra-fields") or []
        if not isinstance(extra, (list, tuple, set, frozenset)):
            return set()
        return {f for f in extra if isinstance(f, str)}

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        known_events = self._known_events()
        extra_fields = self._extra_fields()
        allow_both = bool(self.setting("allow-both-files"))

        blocks = context.lint_tree.find(CodexHooksBlock)
        # The ``hooks.json`` files that declare hooks for Codex to merge —
        # the same test the config side applies to itself, so an empty or
        # unparseable one does not make the claim. Built from the full
        # ``find()`` result, so it must stay outside the loop.
        hooks_files: Set[Path] = set()
        if not allow_both:
            hooks_files = {
                b.resolved_path
                for b in blocks
                if b.path.name == CODEX_HOOKS_FILENAME and _declares_hooks(b)
            }

        for block in blocks:
            if isinstance(block, CodexConfigHooksBlock) and not allow_both:
                violations.extend(self._check_both_files(block, hooks_files))

            if block.parse_error:
                violations.append(
                    self.violation(
                        f"Invalid {block.syntax_name}: {safe_display(block.parse_error)}",
                        file_path=block.path,
                    )
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
                    self.violation(
                        f"'hooks' must be a {block.syntax_name} {block.mapping_noun}",
                        file_path=block.path,
                    )
                )
                continue

            for event, entries in raw_hooks.items():
                violations.extend(
                    self._check_event(event, entries, known_events, extra_fields, block)
                )

        return violations

    def _check_both_files(
        self, block: CodexConfigHooksBlock, hooks_files: Set[Path]
    ) -> List[RuleViolation]:
        """One ``.codex/`` layer declaring hooks in both of its files.

        Benign, and INFO for that reason: measured against codex-cli 0.153.0
        and re-confirmed at 0.153.2, both files load, every handler runs once,
        and Codex prints one startup warning naming both paths. What it costs
        is surprise — a reader editing ``hooks.json`` does not see the
        ``config.toml`` copy firing too. ``allow-both-files`` silences it for a layer that splits
        them deliberately; the rule's page carries the advice about which
        file to keep.

        Per layer, not per repository: a monorepo may keep one directory this
        way and others not.

        Asked of the tree rather than the filesystem: a ``hooks.json`` the
        project excluded is one it chose not to lint.

        Only where both files actually declare an event group, by the same
        :func:`_declares_hooks` test: a file skillsaw attached for its parse
        error, or one whose ``[hooks]`` header stands over nothing, declares
        no hooks for Codex to merge.
        """
        if not _declares_hooks(block):
            return []
        if safe_resolve(block.path.parent / CODEX_HOOKS_FILENAME) not in hooks_files:
            return []
        return [
            self.violation(
                f"Hooks are also declared in {CODEX_HOOKS_FILENAME}; Codex merges both",
                file_path=block.path,
                severity=Severity.INFO,
            )
        ]

    def _check_event(
        self,
        event: Any,
        entries: Any,
        known_events: Set[str],
        extra_fields: Set[str],
        block: CodexHooksBlock,
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
                    f"Hook event '{name}' must have {_with_article(block.sequence_noun)} of hook "
                    "configurations",
                    file_path=block.path,
                )
            )
            return violations

        for index, entry in enumerate(entries):
            violations.extend(
                self._check_entry(name, event, index, entry, extra_fields, block, builtin)
            )
        return violations

    def _check_entry(
        self,
        name: str,
        event: Any,
        index: int,
        entry: Any,
        extra_fields: Set[str],
        block: CodexHooksBlock,
        builtin: bool = True,
    ) -> List[RuleViolation]:
        """One ``{matcher?, hooks: [...]}`` entry under an event."""
        violations: List[RuleViolation] = []
        where = f"{name}[{index}]"

        if not isinstance(entry, dict):
            return [
                self.violation(
                    f"Hook {where} must be {_with_article(block.mapping_noun)}",
                    file_path=block.path,
                )
            ]

        # An event group takes ``matcher`` and ``hooks`` and nothing else.
        # Codex drops anything beside them without a word — measured, under
        # ``--strict-config`` too, which never descends into ``[hooks]`` — so
        # ``mather = "shell"`` silently loses the filter it meant to set.
        violations.extend(self._unknown_keys(where, entry, _ENTRY_FIELDS, extra_fields, block))

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
                self.violation(
                    f"Hook {where} 'hooks' must be {_with_article(block.sequence_noun)}",
                    file_path=block.path,
                )
            ]

        for handler_index, handler in enumerate(handlers):
            violations.extend(
                self._check_handler(
                    f"{where}.hooks[{handler_index}]", event, handler, extra_fields, block
                )
            )
        return violations

    def _check_handler(
        self, where: str, event: Any, handler: Any, extra_fields: Set[str], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """One handler object: its type, then the fields that type takes."""
        if not isinstance(handler, dict):
            return [
                self.violation(
                    f"Hook {where} must be {_with_article(block.mapping_noun)}",
                    file_path=block.path,
                )
            ]

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

        violations = self._check_fields(where, handler_type, handler, extra_fields, block)

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
        self,
        where: str,
        handler_type: str,
        handler: Dict[str, Any],
        extra_fields: Set[str],
        block: CodexHooksBlock,
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
                    self.violation(
                        f"Hook {where} '{field}' must be a str",
                        file_path=block.path,
                    )
                )

        # Whether anything at all is known about this type's fields. Empty
        # for a handler type added to the set without a table beside it, and
        # then every key on it would read as unknown — see the required-field
        # note above.
        if _DECLARED_FIELDS.get(handler_type):
            violations.extend(
                self._unknown_keys(where, handler, _HANDLER_KEYS, extra_fields, block)
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
            if field == _TIMEOUT:
                continue
            for spelling in _FIELD_SPELLINGS.get(field, (field,)):
                if spelling not in handler:
                    continue
                value = handler[spelling]
                if not _matches_type(value, expected):
                    violations.append(
                        self.violation(
                            f"Hook {where} '{spelling}' must be a {expected.__name__}",
                            file_path=block.path,
                        )
                    )
                elif field in block.whole_number_fields and value < 0:
                    violations.append(
                        self.violation(
                            f"Hook {where} '{spelling}' must not be negative, got "
                            f"{safe_display(value)}",
                            file_path=block.path,
                        )
                    )

        violations.extend(self._check_alias_conflicts(where, handler_type, handler, block))

        return violations

    def _unknown_keys(
        self,
        where: str,
        table: Dict[str, Any],
        accepted: AbstractSet[str],
        extra_fields: Set[str],
        block: CodexHooksBlock,
    ) -> List[RuleViolation]:
        """Keys Codex loads the file over and then never reads.

        Silent in both files: measured, an unrecognized key on a handler or
        on an event group is dropped without a word, under
        ``--strict-config`` too, which never descends into ``[hooks]``. So
        nothing but a linter will ever say that a misspelled
        ``commandWindows`` or ``matcher`` does nothing. WARNING because the
        file still loads, and ``extra-fields`` accepts a spelling newer than
        this release.

        One finding per table: the defect is the table, and a handler
        pasted from another host's file would otherwise report every key it
        carries. Bounded by :func:`_sample`, so a crafted file cannot buy a
        message per key.
        """
        unknown = [f for f in table if f not in accepted and f not in extra_fields]
        if not unknown:
            return []
        plural = "s" if len(unknown) > 1 else ""
        return [
            self.violation(
                f"Hook {where} has unknown field{plural} {_sample(unknown)}",
                file_path=block.path,
                severity=Severity.WARNING,
            )
        ]

    def _check_alias_conflicts(
        self, where: str, handler_type: str, handler: Dict[str, Any], block: CodexHooksBlock
    ) -> List[RuleViolation]:
        """Two spellings of one field on the same handler.

        Codex's alias is a second name for a single serde field, so a
        handler carrying both is a duplicate key. Measured against codex-cli
        0.153.2: a ``config.toml`` exits 1 with ``duplicate field
        `commandWindows` `` and a ``hooks.json`` is dropped with the same
        message, so both files lose their hooks over it.

        Only where the handler type owns the field. Measured, a ``mcp_tool``
        handler carrying both spellings loads: neither is a field of that
        variant, so serde flattens both away and there is no duplicate — the
        unknown-field finding above is the whole story there.

        Two spellings are named, and there is one alias per field, so
        naming a pair says everything about a conflict.
        """
        violations = []
        for field in sorted(_DECLARED_FIELDS.get(handler_type, ())):
            spellings = _FIELD_SPELLINGS.get(field)
            if spellings is None:
                continue
            present = [s for s in spellings if s in handler]
            if len(present) > 1:
                violations.append(
                    self.violation(
                        f"Hook {where} sets both '{present[0]}' and '{present[1]}'",
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

        A ``config.toml`` is stricter, and the block says so: Codex
        deserializes the field as a ``u64`` there, measured, so a float and a
        negative are both refusals rather than durations —
        ``timeout = -1`` exits 1 with ``invalid value: integer `-1`, expected
        u64``, where ``timeout = 0`` loads. No upper bound is needed: TOML
        integers stop at ``i64``, below the ``u64`` ceiling.

        Both files deserialize the same ``Option<u64>`` and a ``hooks.json``
        is dropped over a float or a negative just as measurably. The JSON
        path keeps the number ``hooks-json-valid`` shipped, deliberately: it
        is a released check, and tightening it would newly fail files that
        pass today.
        """
        if _TIMEOUT not in handler:
            return []
        timeout = handler[_TIMEOUT]
        whole_only = _TIMEOUT in block.whole_number_fields
        # The type first, then the range: a wrong type is named by its type
        # and a wrong value by its value, so the message says which it is.
        if not is_finite_number(timeout) or (whole_only and isinstance(timeout, float)):
            got: Optional[str] = type(timeout).__name__
        elif whole_only and timeout < 0:
            got = safe_display(timeout)
        else:
            got = None
        if got is not None:
            wanted = "a whole number of seconds" if whole_only else "a number"
            return [
                self.violation(
                    f"Hook {where} 'timeout' must be {wanted}, got {got}",
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
