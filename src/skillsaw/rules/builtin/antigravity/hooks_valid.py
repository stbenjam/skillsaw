"""Rule: antigravity-hooks-valid."""

from __future__ import annotations

from typing import AbstractSet, Any, Dict, List, Optional, Tuple

from skillsaw.blocks import json_token
from skillsaw.blocks.json_config import (
    AntigravityHooksBlock,
    _antigravity_entry_declares_a_handler,
)
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import antigravity
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity

#: Rendered once for the message that reports a bad handler type.
_ACCEPTED_TYPES = " or ".join(f"'{name}'" for name in sorted(antigravity.HOOK_HANDLER_TYPES))

#: Said by every finding about a defect that costs the whole file, because
#: that is the part an author cannot guess: the sibling hooks in the same
#: document stop running too, and ``agy`` still exits 0 while they do.
_FILE_SCOPED = "Antigravity loads no hook from this file"

#: Non-object metadata values fail the named-hook parser, including strings.
_FILE_SCOPED_OR_INERT = (
    "Antigravity reads every top-level key as a hook name, so it loads no runnable hook "
    "from this file"
)


class AntigravityHooksValidRule(Rule):
    """Validate an Antigravity ``hooks.json``.

    Two failure scopes, both measured against ``agy`` 1.1.25 and neither
    obvious from the file:

    * A shape ``agy``'s parser rejects drops the **whole file** — every
      hook in it, not the entry that carries the defect — with one log line
      and exit 0. Nothing tells the author at run time. That is the ERROR
      half.
    * A key ``agy``'s parser does not recognise is **silently ignored**, so
      the hook it configures never runs while the file loads clean. That is
      the WARNING half.

    Advisory findings are held back while a file-scoped defect stands:
    nothing in the file loads, so what an ignored key would have cost is
    not yet a fact about this repository.
    """

    since = "0.20.0"
    # ``enabled: auto`` on the base default, gated on the two places these
    # files live: an Antigravity workspace and an Antigravity plugin.
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

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
        return "antigravity-hooks-valid"

    @property
    def description(self) -> str:
        return "hooks.json must use Antigravity's hook events, handler types and fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def _known_events(self) -> Dict[str, str]:
        """Antigravity's events by casefolded name, plus any the project declares.

        Casefolded because ``agy`` binds event keys case-insensitively:
        ``pretooluse`` reaches ``PreToolUse``, and reporting it as unknown
        would be a false positive on a file that works.

        ``setdefault``, so a declared spelling never displaces a canonical
        name: ``extra-events: [pretooluse]`` would otherwise rebind that
        casefold to the declared spelling, and ``_check_event`` decides group-versus-flat
        by asking whether the canonical name is in
        :data:`~skillsaw.formats.antigravity.TOOL_HOOK_EVENTS` — so a valid
        ``PreToolUse`` group would be read as a flat handler and every key
        in it reported as unknown.

        The declared type is not enforced when the config loads, so
        ``extra-events: 42`` arrives here as an int. Iterating it would
        raise ``TypeError`` and cost every finding in every hooks file over
        one bad config line.
        """
        known = dict(antigravity.HOOK_EVENTS_BY_CASEFOLD)
        extra = self.setting("extra-events") or []
        if isinstance(extra, (list, tuple, set, frozenset)):
            for event in extra:
                if isinstance(event, str):
                    known.setdefault(event.casefold(), event)
        return known

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        known_events = self._known_events()
        for block in context.lint_tree.find(AntigravityHooksBlock):
            violations.extend(_FileCheck(self, block, known_events).run())
        return violations


class _FileCheck:
    """One hooks file, walked once."""

    def __init__(
        self,
        rule: AntigravityHooksValidRule,
        block: AntigravityHooksBlock,
        known_events: Dict[str, str],
    ) -> None:
        self.rule = rule
        self.block = block
        self.known_events = known_events
        self.fatal: List[RuleViolation] = []
        self.advisory: List[RuleViolation] = []

    def _fatal(self, where: str, problem: str) -> None:
        self.fatal.append(
            self.rule.violation(
                f"{where}: {problem}; {_FILE_SCOPED}",
                file_path=self.block.path,
                fingerprint_discriminator=f"{where}:{problem}",
            )
        )

    def _advisory(self, where: str, problem: str) -> None:
        self.advisory.append(
            self.rule.violation(
                f"{where}: {problem}",
                file_path=self.block.path,
                severity=Severity.WARNING,
                fingerprint_discriminator=f"{where}:{problem}",
            )
        )

    def run(self) -> List[RuleViolation]:
        if self.block.has_utf8_bom():
            self._fatal("hooks.json", "remove the UTF-8 BOM so Antigravity can parse the file")
            return self.fatal
        if self.block.parse_error:
            return [
                self.rule.violation(
                    f"hooks.json does not parse: {safe_display(self.block.parse_error)}; "
                    f"{_FILE_SCOPED}",
                    file_path=self.block.path,
                    fingerprint_discriminator="parse-error",
                )
            ]

        # Python's ``json`` accepts the bare tokens ``NaN``, ``Infinity``
        # and ``-Infinity`` as floats where Go's decoder refuses the
        # document, so the defect is the file rather than the field.
        found = self.block.first_non_finite()
        if found is not None:
            path, value = found
            return [
                self.rule.violation(
                    f"'{json_token(value)}' at {safe_display(path)} is not valid JSON; "
                    f"{_FILE_SCOPED}",
                    file_path=self.block.path,
                    fingerprint_discriminator="non-finite",
                )
            ]

        data = self.block.raw_data
        if not isinstance(data, dict):
            return [
                self.rule.violation(
                    f"hooks.json must be a JSON object of named hooks; {_FILE_SCOPED}",
                    file_path=self.block.path,
                    fingerprint_discriminator="root-not-object",
                )
            ]

        foreign = self._foreign_shape(data)
        if foreign is not None:
            return [foreign]

        for hook_name, hook_spec in data.items():
            self._check_named_hook(hook_name, hook_spec)

        # Nothing in the file loads while a file-scoped defect stands, so
        # an ignored key has cost nothing yet.
        return self.fatal or self.advisory

    def _foreign_shape(self, data: Dict[str, Any]) -> Optional[RuleViolation]:
        """Consolidate recognizable foreign nesting into one advisory.

        Non-object metadata siblings identify a foreign document. Without
        metadata, require known events and a group under a flat event;
        tool-event groups and direct handlers can be valid named hooks.
        Null siblings are accepted by the loader. A top-level ``enabled``
        remains an ordinary hook name, with its own type diagnostic.
        """
        nested = data.get("hooks")
        if not isinstance(nested, dict) or not nested:
            return None
        siblings = {
            key: value for key, value in data.items() if key != "hooks" and value is not None
        }
        if siblings:
            if "enabled" in siblings or any(isinstance(value, dict) for value in siblings.values()):
                return None
            return self._foreign_violation(_FILE_SCOPED_OR_INERT)

        # Branch (a): ``hooks`` alone, and its keys must be this host's
        # events — otherwise it is an ordinary hook named ``hooks``.
        events = {}
        for key, value in nested.items():
            # JSON object keys are always strings, so no type guard here.
            canonical = self.known_events.get(key.casefold())
            if canonical is None:
                return None
            events[canonical] = value
        if any(
            canonical in antigravity.FLAT_HOOK_EVENTS
            and isinstance(entries, list)
            and any(
                isinstance(entry, dict)
                and isinstance(entry.get("hooks"), list)
                and not _antigravity_entry_declares_a_handler(entry)
                for entry in entries
            )
            for canonical, entries in events.items()
        ):
            return self._foreign_violation(
                "Antigravity reads every top-level key as a hook name, so this declares one "
                "hook called 'hooks' whose entries carry no command"
            )
        return None

    def _foreign_violation(self, consequence: str) -> RuleViolation:
        return self.rule.violation(
            f"this hooks.json is written in another host's nested shape; {consequence}",
            file_path=self.block.path,
            # Hardcoded, against the house rule that severity stays
            # configurable: the shape says the file targets another tool,
            # and an ERROR would fail CI for a repository that never
            # configured Antigravity and put this file in a directory name
            # four ecosystems share.
            severity=Severity.WARNING,
            fingerprint_discriminator="foreign-shape",
        )

    def _check_named_hook(self, hook_name: Any, hook_spec: Any) -> None:
        where = f"hook '{safe_display(str(hook_name))}'"
        if hook_spec is None:
            # Go decodes a JSON ``null`` as the zero value and reports
            # nothing, so every ``null`` in this file reads as "the key is
            # absent". Measured at every placement: the file still loads.
            return
        if not isinstance(hook_spec, dict):
            hint = antigravity.HOOK_METADATA_KEY_HINTS.get(hook_name)
            if hint is not None:
                # Every top-level key is a hook *name*, so there is no
                # file-level metadata to write here. The author who wrote
                # some meant to configure the file and instead broke it.
                self._fatal(
                    "hooks.json",
                    f"'{safe_display(str(hook_name))}' at the top level is read as a hook name, "
                    f"not a setting; {hint}",
                )
                return
            self._fatal(where, "a named hook must be a JSON object")
            return
        # An object value under that name is an ordinary hook and loads:
        # measured, ``{"enabled": {"Stop": [...]}}`` reads ``loaded 1 named
        # hooks``. Only the value decides, so it falls through to the
        # checks every other named hook gets.

        for key, value in hook_spec.items():
            if key in antigravity.HOOK_SPEC_NON_EVENT_KEYS:
                if value is not None and not isinstance(value, bool):
                    self._fatal(where, f"'{safe_display(str(key))}' must be a boolean")
                continue
            self._check_event(where, key, value)

    def _check_event(self, where: str, event: Any, value: Any) -> None:
        canonical = self.known_events.get(event.casefold()) if isinstance(event, str) else None
        if canonical is None:
            self._advisory(
                where,
                f"event '{safe_display(str(event))}' is not one Antigravity dispatches, "
                "so its hooks never run",
            )
            return
        # Sanitized because ``canonical`` can come from ``extra-events``, so
        # a ``.skillsaw.yaml`` string reaches terminal, JSON and SARIF
        # output the way a repository-supplied one would.
        event_where = f"{where} {safe_display(canonical)}"
        if value is None:
            return
        if not isinstance(value, list):
            self._fatal(event_where, "an event's value must be an array")
            return
        grouped = canonical in antigravity.TOOL_HOOK_EVENTS
        for index, entry in enumerate(value):
            entry_where = f"{event_where}[{index}]"
            if entry is None:
                continue
            if not isinstance(entry, dict):
                self._fatal(
                    entry_where,
                    (
                        "a hook group must be a JSON object"
                        if grouped
                        else "a handler must be a JSON object"
                    ),
                )
                continue
            if grouped or (canonical not in antigravity.FLAT_HOOK_EVENTS and "hooks" in entry):
                self._check_group(entry_where, entry)
            else:
                self._check_handler(entry_where, entry)

    def _check_group(self, where: str, group: Dict[str, Any]) -> None:
        matcher = group.get("matcher")
        if matcher is not None and not isinstance(matcher, str):
            self._fatal(where, "'matcher' must be a string")
        self._report_unknown_keys(where, group, antigravity.HOOK_GROUP_KEYS, "group key")
        handlers = group.get("hooks")
        if handlers is None:
            return
        if not isinstance(handlers, list):
            self._fatal(where, "'hooks' must be an array of handlers")
            return
        for index, handler in enumerate(handlers):
            handler_where = f"{where}.hooks[{index}]"
            if handler is None:
                continue
            if not isinstance(handler, dict):
                self._fatal(handler_where, "a handler must be a JSON object")
                continue
            self._check_handler(handler_where, handler)

    def _check_handler(self, where: str, handler: Dict[str, Any]) -> None:
        handler_type, typed = self._handler_type(where, handler)
        for field in ("command", "prompt", "model"):
            if handler.get(field) is not None and not isinstance(handler[field], str):
                self._fatal(where, f"'{field}' must be a string")
                typed = False
        timeout = handler.get("timeout")
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, int):
                # An int32 in Go: ``0`` and negatives load, a float or a
                # string kills the file.
                self._fatal(where, "'timeout' must be a whole number of seconds")
            elif not antigravity.HOOK_TIMEOUT_MIN <= timeout <= antigravity.HOOK_TIMEOUT_MAX:
                # Measured: an integer past either end of the int32 range
                # empties the file exactly as a float does.
                self._fatal(
                    where,
                    f"'timeout' must be between {antigravity.HOOK_TIMEOUT_MIN} and "
                    f"{antigravity.HOOK_TIMEOUT_MAX}",
                )

        self._report_unknown_keys(where, handler, antigravity.HOOK_HANDLER_KEYS, "handler key")

        if not typed or handler_type is None:
            return
        if handler_type == "command":
            # Truthiness, not presence: ``""`` is Go's zero value for a
            # string field and reads as the key being absent, so
            # ``{"command": "echo ok", "prompt": ""}`` loads (measured).
            # A non-string value already failed the type loop above.
            for forbidden in ("prompt", "model"):
                if handler.get(forbidden):
                    self._fatal(where, f"a command hook may not carry '{forbidden}'")
            command = handler.get("command")
            if not (isinstance(command, str) and command.strip()):
                self._advisory(where, "a command hook with no command runs nothing")
        elif handler_type == "prompt" and handler.get("command"):
            self._fatal(where, "a prompt hook may not carry 'command'")

    def _handler_type(self, where: str, handler: Dict[str, Any]) -> Tuple[Optional[str], bool]:
        """The handler's effective type, and whether it was well formed.

        An absent, ``null`` or empty ``type`` is a command hook — the
        spelling the vendor's own examples use. Any other value fails the
        file, and the comparison is case-sensitive: ``"COMMAND"`` is
        rejected.
        """
        raw = handler.get("type")
        if raw is None:
            return "command", True
        if not isinstance(raw, str):
            self._fatal(where, "'type' must be a string")
            return None, False
        if raw == "":
            return "command", True
        if raw not in antigravity.HOOK_HANDLER_TYPES:
            self._fatal(
                where,
                f"handler type '{safe_display(raw)}' is not supported; use {_ACCEPTED_TYPES}",
            )
            return None, False
        return raw, True

    def _report_unknown_keys(
        self, where: str, obj: Dict[str, Any], known: AbstractSet[str], label: str
    ) -> None:
        """One finding per object, listing every key its parser discards."""
        unknown = sorted(str(key) for key in obj if key not in known)
        if not unknown:
            return
        rendered = ", ".join(f"'{safe_display(key)}'" for key in unknown)
        if len(unknown) > 1:
            self._advisory(where, f"unknown {label}s {rendered} are ignored")
        else:
            self._advisory(where, f"unknown {label} {rendered} is ignored")
