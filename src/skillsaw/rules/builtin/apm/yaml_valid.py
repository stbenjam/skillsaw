"""
Rule: apm-yaml-valid
"""

from typing import List

import yaml

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import ApmConfigNode
from skillsaw.rules.builtin.utils import read_text

from ._helpers import _yaml_key_line


class ApmYamlValidRule(Rule):
    """Validate that apm.yml exists and has required fields"""

    repo_types = None  # runs when enabled; auto-enable via config + has_apm check

    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "apm-yaml-valid"

    @property
    def description(self) -> str:
        return "apm.yml must exist with valid YAML and required fields (name, version, description)"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        if not context.has_apm:
            return []

        config_nodes = context.lint_tree.find(ApmConfigNode)
        if not config_nodes:
            return [
                self.violation(
                    "Missing apm.yml at repository root (required for APM repos)",
                )
            ]

        violations = []
        apm_yml = config_nodes[0].path

        content = read_text(apm_yml)
        if content is None:
            violations.append(
                self.violation(
                    "Failed to read apm.yml (invalid encoding or I/O error)",
                    file_path=apm_yml,
                )
            )
            return violations

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            violations.append(
                self.violation(
                    f"Invalid YAML in apm.yml: {e}",
                    file_path=apm_yml,
                )
            )
            return violations

        if not isinstance(data, dict):
            violations.append(
                self.violation(
                    "apm.yml must be a YAML mapping",
                    file_path=apm_yml,
                )
            )
            return violations

        # Required fields
        for field in ("name", "version", "description"):
            if field not in data:
                violations.append(
                    self.violation(
                        f"Missing required field '{field}' in apm.yml",
                        file_path=apm_yml,
                    )
                )
                continue
            value = data[field]
            if not isinstance(value, str):
                violations.append(
                    self.violation(
                        f"Field '{field}' must be a string in apm.yml",
                        file_path=apm_yml,
                        line=_yaml_key_line(apm_yml, field),
                    )
                )

        return violations
