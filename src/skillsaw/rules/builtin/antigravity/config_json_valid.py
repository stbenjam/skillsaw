"""Rule: antigravity-config-json-valid."""

from __future__ import annotations

from typing import Any, List

from skillsaw.blocks import json_token
from skillsaw.blocks.json_config import AntigravityConfigBlock
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity

_SKIPPED = "Antigravity logs one line and loads nothing from this registry"


class AntigravityConfigJsonValidRule(Rule):
    """Validate an Antigravity registry file.

    ``agents.json``, ``plugins.json``, ``skills.json`` and
    ``workflows.json`` each name *where else* to load that kind of
    customization from: ``{"entries": [{"path", "include_only",
    "exclude"}], "inherits": [...]}``. A non-object root logs one
    ``Failed to load JSON config file`` line and the file is skipped;
    ``agy`` still exits 0.

    Opt-in, because only two of the four registries were reachable
    offline: ``agy agents`` queries the agents and plugins kinds and no
    subcommand exercises the others, so the checks below stop at what a
    measurement covers — the document parses, its root is an object, and
    ``entries`` holds objects with a string ``path``. Whether a listed path
    resolves is deliberately not asked.
    """

    since = "0.20.0"
    default_enabled = False
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

    @property
    def rule_id(self) -> str:
        return "antigravity-config-json-valid"

    @property
    def description(self) -> str:
        return (
            "Antigravity registry files must parse as an object whose 'entries' "
            "are objects with a string 'path'"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(AntigravityConfigBlock):
            violations.extend(self._check_file(block))
        return violations

    def _check_file(self, block: AntigravityConfigBlock) -> List[RuleViolation]:
        name = block.path.name
        if block.parse_error:
            return [
                self.violation(
                    f"{name} does not parse: {safe_display(block.parse_error)}; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="parse-error",
                )
            ]
        found = block.first_non_finite()
        if found is not None:
            path, value = found
            return [
                self.violation(
                    f"'{json_token(value)}' at {safe_display(path)} is not valid JSON; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="non-finite",
                )
            ]
        data = block.raw_data
        if not isinstance(data, dict):
            return [
                self.violation(
                    f"{name} must be a JSON object; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="root-not-object",
                )
            ]

        entries = data.get("entries")
        if entries is None:
            return []
        if not isinstance(entries, list):
            return [
                self.violation(
                    f"{name}: 'entries' must be an array",
                    file_path=block.path,
                    fingerprint_discriminator="entries-not-array",
                )
            ]
        return self._check_entries(block, name, entries)

    def _check_entries(
        self, block: AntigravityConfigBlock, name: str, entries: List[Any]
    ) -> List[RuleViolation]:
        """One finding for the whole file, naming the first few positions.

        A registry written to the wrong shape is wrong in every entry, and
        a finding per entry would bury the one thing an author has to
        change.
        """
        bad = [
            index
            for index, entry in enumerate(entries)
            if not (isinstance(entry, dict) and isinstance(entry.get("path"), str))
        ]
        if not bad:
            return []
        shown = ", ".join(f"entries[{index}]" for index in bad[:3])
        more = f" and {len(bad) - 3} more" if len(bad) > 3 else ""
        return [
            self.violation(
                f"{name}: {shown}{more} must be an object with a string 'path' naming the "
                "directory of items to load",
                file_path=block.path,
                fingerprint_discriminator="entry-shape",
            )
        ]
