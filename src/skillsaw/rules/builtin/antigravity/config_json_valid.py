"""Rule: antigravity-config-json-valid."""

from __future__ import annotations

from typing import List

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
    "exclude"}], "inherits": [...]}``. A non-null, non-object root logs one
    ``Failed to load JSON config file`` line and the file is skipped;
    ``agy`` still exits 0.

    Opt-in, because only two of the four registries were reachable
    offline: ``agy agents`` queries the agents and plugins kinds and no
    subcommand exercises the others, so the checks below stop at what a
    measurement covers — the document parses, its root is an object or null,
    and ``entries`` / ``inherits`` contain correctly typed paths and filters.
    Whether a listed path resolves is deliberately not asked: a registry may
    name a directory that exists only on a developer's machine, and this rule is opt-in
    while the lint tree is not.

    The *tree* does resolve them, for the two registries measured to load
    what they name — a ``plugins.json`` entry's plugins get containers and
    a ``agents.json`` entry's ``*.md`` attaches as agent prose — so the
    security and content rules read customization a repository ships
    outside its customization root whether or not this rule runs.
    """

    since = "0.20.0"
    default_enabled = False
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

    @property
    def rule_id(self) -> str:
        return "antigravity-config-json-valid"

    @property
    def description(self) -> str:
        return "Antigravity registry files must decode their paths and filters correctly"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(AntigravityConfigBlock):
            violations.extend(self._check_file(block))
        return violations

    def _check_file(self, block: AntigravityConfigBlock) -> List[RuleViolation]:
        name = block.path.name
        if block.has_utf8_bom():
            return [
                self.violation(
                    f"{name}: remove the UTF-8 BOM so Antigravity can parse the file; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="utf8-bom",
                )
            ]
        if block.parse_error:
            return [
                self.violation(
                    f"{name} does not parse: {safe_display(block.parse_error)}; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="parse-error",
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

        errors = getattr(data, "decode_errors", [])
        if errors:
            grouped = {}
            for where, problem in errors:
                grouped.setdefault(problem, []).append(where)
            details = []
            for problem, positions in grouped.items():
                positions = list(dict.fromkeys(positions))
                shown = ", ".join(positions[:3])
                more = f" and {len(positions) - 3} more" if len(positions) > 3 else ""
                details.append(f"{shown}{more} {problem}")
            return [
                self.violation(
                    f"{name}: {safe_display('; '.join(details))}; {_SKIPPED}",
                    file_path=block.path,
                    fingerprint_discriminator="field-type",
                )
            ]

        return []
