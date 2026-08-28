"""
Rule: roo-modes-valid
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from skillsaw.blocks import RooModesBlock
from skillsaw.context import HAS_ROO, RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import commented_item_line, commented_key_line

#: Roo Code's own slug validator: ASCII letters, digits and hyphens. It is
#: laxer than kebab-case (``Docs-Writer`` passes), so this rule reports only
#: what Roo itself rejected rather than imposing a house style on top.
_SLUG = re.compile(r"^[a-zA-Z0-9-]+$")

#: The tool groups Roo Code's schema accepts. An unrecognised name fails
#: validation, so the mode does not load at all.
_TOOL_GROUPS = ("read", "edit", "command", "mcp", "modes")

#: Accepted for compatibility and then dropped before validation, so a mode
#: that names one silently gets nothing from it.
_DEPRECATED_GROUPS = ("browser",)

#: Required on every custom mode; a mode missing one does not load.
_REQUIRED_STRINGS = ("slug", "name", "roleDefinition")

#: Present-and-optional, but still has to be a string when present.
_OPTIONAL_STRINGS = ("whenToUse", "description", "customInstructions")

#: Every key Roo Code's published ``schemas/roomodes.json`` allows on a mode.
#: That schema is strict, so an editor validating against it rejects a key
#: outside this set — while the runtime reader ignores it, which is the
#: silent half: a misspelled ``whenToUse`` costs the mode its routing text
#: and nothing says so. ``source`` and ``rulesFiles`` are in the schema but
#: system-managed: the loader overwrites ``source``, and ``rulesFiles``
#: carries content only in an exported mode.
_KNOWN_MODE_KEYS = frozenset(
    _REQUIRED_STRINGS + _OPTIONAL_STRINGS + ("groups", "source", "rulesFiles")
)


class RooModesValidRule(Rule):
    """Validate the legacy Roo Code .roomodes custom-mode definitions"""

    since = "0.20.0"

    formats = frozenset({HAS_ROO})

    config_schema = {
        "require-when-to-use": {
            "type": "bool",
            "default": False,
            "description": (
                "Require every custom mode to declare 'whenToUse', the text an "
                "orchestrator reads when deciding to delegate to the mode"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "roo-modes-valid"

    @property
    def description(self) -> str:
        return "Roo .roomodes custom modes must declare the fields Roo needs to load them"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        require_when_to_use = self.setting("require-when-to-use")
        for block in context.lint_tree.find(RooModesBlock):
            violations.extend(self._check_file(block, require_when_to_use))
        return violations

    def _check_file(self, block: RooModesBlock, require_when_to_use: bool) -> List[RuleViolation]:
        if block.parse_error:
            # The only error-severity finding: Roo cannot read a single mode
            # out of a document that does not parse, so every mode the file
            # declares is gone. Parser diagnostics quote source text the
            # malformed document controls, so redact like any value echo.
            return [
                self._report(
                    block,
                    f"Invalid YAML: {safe_display(block.parse_error)} — Roo loads no mode "
                    "from this file",
                    line=block.error_line,
                    severity=Severity.ERROR,
                )
            ]

        data = block.raw_data
        if data is None:
            # An empty document declares nothing. Roo falls back to its
            # built-in modes, which is a legitimate state for a file left
            # behind by a tool that no longer runs.
            return []
        if not isinstance(data, dict):
            return [
                self._report(block, ".roomodes must be a YAML mapping with a 'customModes' key")
            ]

        modes = data.get("customModes")
        if modes is None:
            return [
                self._report(
                    block,
                    "No 'customModes' key: the file declares no mode Roo can load",
                )
            ]
        if not isinstance(modes, list):
            return [
                self._report(
                    block,
                    f"'customModes' must be a list, got {type(modes).__name__}",
                    line=commented_key_line(data, "customModes"),
                )
            ]

        violations: List[RuleViolation] = []
        seen_slugs: Set[str] = set()
        for index, mode in enumerate(modes):
            violations.extend(
                self._check_mode(
                    block,
                    mode,
                    index,
                    commented_item_line(modes, index),
                    seen_slugs,
                    require_when_to_use,
                )
            )
        return violations

    def _check_mode(
        self,
        block: RooModesBlock,
        mode: Any,
        index: int,
        item_line: Optional[int],
        seen_slugs: Set[str],
        require_when_to_use: bool,
    ) -> List[RuleViolation]:
        where = f"customModes[{index}]"
        if not isinstance(mode, dict):
            return [
                self._report(
                    block, f"{where} must be a mapping, got {type(mode).__name__}", line=item_line
                )
            ]

        violations: List[RuleViolation] = []
        for key in _REQUIRED_STRINGS:
            value = mode.get(key)
            line = commented_key_line(mode, key) or item_line
            if value is None:
                violations.append(
                    self._report(block, f"{where} is missing required '{key}'", line=line)
                )
            elif not isinstance(value, str) or not value.strip():
                violations.append(
                    self._report(block, f"{where}.{key} must be a non-empty string", line=line)
                )

        for key in _OPTIONAL_STRINGS:
            value = mode.get(key)
            if value is not None and not isinstance(value, str):
                violations.append(
                    self._report(
                        block,
                        f"{where}.{key} must be a string, got {type(value).__name__}",
                        line=commented_key_line(mode, key) or item_line,
                    )
                )

        if require_when_to_use and not mode.get("whenToUse"):
            violations.append(
                self._report(
                    block,
                    f"{where} does not declare 'whenToUse', so an orchestrator has "
                    "nothing to read when deciding to delegate to this mode",
                    line=item_line,
                )
            )

        for key in mode:
            if isinstance(key, str) and key not in _KNOWN_MODE_KEYS:
                violations.append(
                    self._report(
                        block,
                        f"{where}: unknown key '{safe_display(str(key))}' — Roo ignores it "
                        "and its published schema rejects the file",
                        line=commented_key_line(mode, key) or item_line,
                    )
                )

        violations.extend(self._check_slug(block, mode, where, item_line, seen_slugs))
        violations.extend(self._check_groups(block, mode, where, item_line))
        return violations

    def _check_slug(
        self,
        block: RooModesBlock,
        mode: dict,
        where: str,
        item_line: Optional[int],
        seen_slugs: Set[str],
    ) -> List[RuleViolation]:
        slug = mode.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            # Already reported as a missing/blank required field.
            return []
        line = commented_key_line(mode, "slug") or item_line
        if not _SLUG.match(slug):
            return [
                self._report(
                    block,
                    f"{where}.slug '{safe_display(slug)}' must use only letters, digits "
                    "and hyphens",
                    line=line,
                )
            ]
        if slug in seen_slugs:
            # Not a last-one-wins merge: Roo's schema rejects a document
            # whose slugs repeat, so one duplicate costs every mode in the
            # file, not just the shadowed one.
            return [
                self._report(
                    block,
                    f"{where}.slug '{safe_display(slug)}' is declared twice — Roo rejects "
                    "a .roomodes with duplicate slugs, so no mode in it loads",
                    line=line,
                )
            ]
        seen_slugs.add(slug)
        return []

    def _check_groups(
        self, block: RooModesBlock, mode: dict, where: str, item_line: Optional[int]
    ) -> List[RuleViolation]:
        groups = mode.get("groups")
        line = commented_key_line(mode, "groups") or item_line
        if groups is None:
            return [self._report(block, f"{where} is missing required 'groups'", line=line)]
        if not isinstance(groups, list):
            return [
                self._report(
                    block,
                    f"{where}.groups must be a list, got {type(groups).__name__}",
                    line=line,
                )
            ]

        violations: List[RuleViolation] = []
        seen_groups: Set[str] = set()
        for position, entry in enumerate(groups):
            entry_line = commented_item_line(groups, position) or line
            label = f"{where}.groups[{position}]"
            if isinstance(entry, str):
                violations.extend(
                    self._check_group_name(block, label, entry, entry_line, seen_groups)
                )
                continue
            if not isinstance(entry, list):
                violations.append(
                    self._report(
                        block,
                        f"{label} must be a tool group name or a [name, options] pair, "
                        f"got {type(entry).__name__}",
                        line=entry_line,
                    )
                )
                continue
            # The restricted form: ["edit", {fileRegex: ..., description: ...}].
            if len(entry) != 2 or not isinstance(entry[0], str):
                violations.append(
                    self._report(
                        block,
                        f"{label} must be a [name, options] pair",
                        line=entry_line,
                    )
                )
                continue
            violations.extend(
                self._check_group_name(block, label, entry[0], entry_line, seen_groups)
            )
            options = entry[1]
            if not isinstance(options, dict):
                violations.append(
                    self._report(
                        block,
                        f"{label} options must be a mapping, got {type(options).__name__}",
                        line=entry_line,
                    )
                )
                continue
            for key in ("fileRegex", "description"):
                value = options.get(key)
                if value is not None and not isinstance(value, str):
                    violations.append(
                        self._report(
                            block,
                            f"{label}.{key} must be a string, got {type(value).__name__}",
                            line=commented_key_line(options, key) or entry_line,
                        )
                    )
        return violations

    def _check_group_name(
        self,
        block: RooModesBlock,
        label: str,
        name: str,
        line: Optional[int],
        seen_groups: Set[str],
    ) -> List[RuleViolation]:
        """One tool group name, in either the bare or the pair form."""
        if name in _DEPRECATED_GROUPS:
            return [
                self._report(
                    block,
                    f"{label}: '{safe_display(name)}' is a retired tool group — Roo strips "
                    "it before loading, so the mode gains nothing from it",
                    line=line,
                )
            ]
        if name not in _TOOL_GROUPS:
            return [
                self._report(
                    block,
                    f"{label}: unknown tool group '{safe_display(name)}' — expected one of "
                    + ", ".join(_TOOL_GROUPS),
                    line=line,
                )
            ]
        if name in seen_groups:
            return [
                self._report(
                    block,
                    f"{label}: '{name}' is listed twice — Roo rejects a mode with a "
                    "repeated tool group",
                    line=line,
                )
            ]
        seen_groups.add(name)
        return []

    def _report(
        self,
        block: RooModesBlock,
        message: str,
        line: Optional[int] = None,
        severity: Severity = Severity.WARNING,
    ) -> RuleViolation:
        """One violation on *block*.

        Everything but an unparseable document is a warning: Roo Code no
        longer runs, so a defect here costs a repository whatever tool
        migrates the file next, not a build.
        """
        return self.violation(message, file_path=block.path, line=line, severity=severity)
