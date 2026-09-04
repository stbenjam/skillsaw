"""Rule: antigravity-plugin-json-valid."""

from __future__ import annotations

from typing import List

from skillsaw.context import RepositoryContext
from skillsaw.formats.antigravity import validate_antigravity_manifest
from skillsaw.lint_target import AntigravityPluginConfigNode
from skillsaw.paths import safe_is_file
from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.utils import read_json_strict


class AntigravityPluginJsonValidRule(Rule):
    """Validate Antigravity plugin manifest (plugin.json)."""

    since = "0.20.0"
    default_enabled = "auto"
    repo_types = frozenset({RepositoryType.ANTIGRAVITY_PLUGIN, RepositoryType.ANTIGRAVITY})

    @property
    def rule_id(self) -> str:
        return "antigravity-plugin-json-valid"

    @property
    def description(self) -> str:
        return "plugin.json must declare a valid Antigravity plugin manifest"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for target in context.lint_tree.find(AntigravityPluginConfigNode):
            if not safe_is_file(target.path):
                violations.append(
                    self.violation(
                        "plugin.json: missing manifest file",
                        file_path=target.path,
                        fingerprint_discriminator="missing manifest file",
                    )
                )
                continue

            data, error = read_json_strict(target.path)
            if error:
                violations.append(
                    self.violation(
                        f"plugin.json: {error}",
                        file_path=target.path,
                        fingerprint_discriminator=error,
                    )
                )
                continue

            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "plugin.json: manifest root must be a JSON object",
                        file_path=target.path,
                        fingerprint_discriminator="manifest root must be a JSON object",
                    )
                )
                continue

            for err in validate_antigravity_manifest(data):
                violations.append(
                    self.violation(
                        f"plugin.json: {err}",
                        file_path=target.path,
                        fingerprint_discriminator=err,
                    )
                )

        return violations
