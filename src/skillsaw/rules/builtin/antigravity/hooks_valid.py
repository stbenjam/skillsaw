"""Rule: antigravity-hooks-valid."""

from __future__ import annotations

from typing import List

from skillsaw.blocks.json_config import AntigravityHooksBlock
from skillsaw.context import RepositoryContext
from skillsaw.formats.antigravity import validate_antigravity_hooks
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity


class AntigravityHooksValidRule(Rule):
    """Validate Antigravity lifecycle hooks file (hooks.json)."""

    since = "0.20.0"
    default_enabled = "auto"
    repo_types = frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN})

    config_schema = {
        "extra-events": {
            "type": "list",
            "default": [],
            "description": "Additional valid hook event names to permit beyond built-in events",
        },
    }

    @property
    def rule_id(self) -> str:
        return "antigravity-hooks-valid"

    @property
    def description(self) -> str:
        return "hooks.json must declare valid Antigravity lifecycle hooks"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        extra_events = self.setting("extra-events")
        if not isinstance(extra_events, (list, tuple, set)):
            extra_events = []
        extra_events_set = set(extra_events)

        for block in context.lint_tree.find(AntigravityHooksBlock):
            found = block.first_non_finite()
            if found is not None:
                non_path, val = found
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message=f"hooks.json: JSON standard forbids non-finite number at {non_path}",
                        file_path=block.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator=non_path,
                    )
                )
                continue

            if block.parse_error:
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message=f"hooks.json: {block.parse_error}",
                        file_path=block.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="parse-error",
                    )
                )
                continue

            if not isinstance(block.raw_data, dict):
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message="hooks.json: must be a JSON object",
                        file_path=block.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="must be a JSON object",
                    )
                )
                continue

            for err in validate_antigravity_hooks(block.raw_data, extra_events=extra_events_set):
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message=f"hooks.json: {err}",
                        file_path=block.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator=err,
                    )
                )

        return violations
