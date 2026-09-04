"""Rule: antigravity-config-json-valid."""

from __future__ import annotations

from typing import List

from skillsaw.blocks import AntigravityConfigBlock
from skillsaw.context import RepositoryContext
from skillsaw.formats.antigravity import validate_antigravity_config
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity


class AntigravityConfigJsonValidRule(Rule):
    """Validate Antigravity skills.json, agents.json, and rules.json configurations."""

    default_enabled = False
    repo_types = frozenset({RepositoryType.ANTIGRAVITY_PLUGIN, RepositoryType.ANTIGRAVITY})
    since = "0.20.0"

    @property
    def rule_id(self) -> str:
        return "antigravity-config-json-valid"

    @property
    def description(self) -> str:
        return (
            "Antigravity skills.json, agents.json, and rules.json must conform to the "
            "Antigravity JSON config specification"
        )

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(AntigravityConfigBlock):
            if block.parse_error is not None:
                violations.append(
                    self.violation(
                        f"{block.path.name}: {block.parse_error}",
                        file_path=block.path,
                        fingerprint_discriminator=block.parse_error,
                    )
                )
                continue

            found = block.first_non_finite()
            if found is not None:
                non_path, val = found
                violations.append(
                    self.violation(
                        f"{block.path.name}: JSON standard forbids non-finite number at {non_path}",
                        file_path=block.path,
                        fingerprint_discriminator=non_path,
                    )
                )
                continue

            if not isinstance(block.raw_data, dict):
                violations.append(
                    self.violation(
                        f"{block.path.name}: expected JSON object (mapping) at root",
                        file_path=block.path,
                    )
                )
                continue

            errors = validate_antigravity_config(block.raw_data)
            for err in errors:
                violations.append(
                    self.violation(
                        f"{block.path.name}: {err}",
                        file_path=block.path,
                        fingerprint_discriminator=err,
                    )
                )

        return violations
