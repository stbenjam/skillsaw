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
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for target in context.lint_tree.find(AntigravityPluginConfigNode):
            if not safe_is_file(target.path):
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message="plugin.json: missing manifest file",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="missing manifest file",
                    )
                )
                continue

            data, error = read_json_strict(target.path)
            if error:
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message=f"plugin.json: {error}",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator=error,
                    )
                )
                continue

            if hasattr(target, "first_non_finite"):
                non_finite = target.first_non_finite()
                if non_finite is not None:
                    path, val = non_finite
                    err = f"non-finite number '{val}' at {path}"
                    violations.append(
                        RuleViolation(
                            rule_id=self.rule_id,
                            message=f"plugin.json: {err}",
                            file_path=target.path,
                            severity=self.default_severity(),
                            fingerprint_discriminator=err,
                        )
                    )
                    continue

            if not isinstance(data, dict):
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message="plugin.json: manifest root must be a JSON object",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="manifest root must be a JSON object",
                    )
                )
                continue

            if "name" not in data:
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message="plugin.json: missing required field 'name'",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="missing required field 'name'",
                    )
                )

            if "version" not in data:
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message="plugin.json: missing required field 'version'",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator="missing required field 'version'",
                    )
                )

            for err in validate_antigravity_manifest(data):
                violations.append(
                    RuleViolation(
                        rule_id=self.rule_id,
                        message=f"plugin.json: {err}",
                        file_path=target.path,
                        severity=self.default_severity(),
                        fingerprint_discriminator=err,
                    )
                )

        return violations
