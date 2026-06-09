"""
Rule: plugin-json-valid
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES


class PluginJsonValidRule(Rule):
    """Check that plugin.json is valid and has required fields"""

    repo_types = PLUGIN_REPO_TYPES

    DEFAULT_RECOMMENDED_FIELDS = ["description", "version", "author"]
    config_schema = {
        "recommended-fields": {
            "type": "list",
            "default": DEFAULT_RECOMMENDED_FIELDS,
            "description": "Fields that trigger a warning if missing from plugin.json",
        },
    }

    @property
    def rule_id(self) -> str:
        return "plugin-json-valid"

    @property
    def description(self) -> str:
        return "plugin.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        recommended_fields = self.config.get("recommended-fields", self.DEFAULT_RECOMMENDED_FIELDS)

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_path = plugin_node.path
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"

            if not plugin_json.exists():
                continue  # Handled by plugin-json-required rule

            # Try to parse JSON
            data, error = read_json(plugin_json)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=plugin_json))
                continue

            if not isinstance(data, dict):
                violations.append(
                    self.violation("Expected JSON object in plugin.json", file_path=plugin_json)
                )
                continue

            # Check required fields
            required_fields = ["name"]
            for field in required_fields:
                if field not in data:
                    violations.append(
                        self.violation(f"Missing required field '{field}'", file_path=plugin_json)
                    )

            # Check recommended fields (warning)
            for field in recommended_fields:
                if field not in data:
                    violations.append(
                        self.violation(
                            f"Missing recommended field '{field}'",
                            file_path=plugin_json,
                            severity=Severity.WARNING,
                        )
                    )

            # Validate version format (semver)
            if "version" in data:
                version = data["version"]
                if not re.match(
                    r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$", str(version)
                ):
                    violations.append(
                        self.violation(
                            f"Version '{version}' should follow semver (X.Y.Z)",
                            file_path=plugin_json,
                        )
                    )

            # Validate author structure
            if "author" in data:
                author = data["author"]
                if not isinstance(author, dict) or "name" not in author:
                    violations.append(
                        self.violation(
                            "Author must be an object with 'name' field",
                            file_path=plugin_json,
                        )
                    )

        return violations
