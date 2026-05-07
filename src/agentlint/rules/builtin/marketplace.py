"""
Rules for validating marketplace structure
"""

import json
from typing import List

from agentlint.rule import Rule, RuleViolation, Severity
from agentlint.context import RepositoryContext, RepositoryType


class MarketplaceJsonValidRule(Rule):
    """Check that marketplace.json is valid"""

    @property
    def rule_id(self) -> str:
        return "marketplace-json-valid"

    @property
    def description(self) -> str:
        return "Marketplace.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Only check if marketplace exists
        if context.repo_type != RepositoryType.MARKETPLACE:
            return violations

        marketplace_file = context.root_path / ".claude-plugin" / "marketplace.json"

        if not marketplace_file.exists():
            violations.append(
                self.violation("Marketplace file not found", file_path=marketplace_file)
            )
            return violations

        # Try to parse
        try:
            with open(marketplace_file, "r") as f:
                marketplace = json.load(f)
        except json.JSONDecodeError as e:
            violations.append(self.violation(f"Invalid JSON: {e}", file_path=marketplace_file))
            return violations
        except IOError as e:
            violations.append(
                self.violation(f"Failed to read file: {e}", file_path=marketplace_file)
            )
            return violations

        # Validate that marketplace is a dictionary
        if not isinstance(marketplace, dict):
            violations.append(
                self.violation(
                    "Marketplace file must contain a JSON object", file_path=marketplace_file
                )
            )
            return violations

        # Validate required fields
        if "name" not in marketplace:
            violations.append(self.violation("Missing 'name' field", file_path=marketplace_file))

        if "owner" not in marketplace:
            violations.append(self.violation("Missing 'owner' field", file_path=marketplace_file))

        if "plugins" not in marketplace:
            violations.append(self.violation("Missing 'plugins' array", file_path=marketplace_file))
        elif not isinstance(marketplace["plugins"], list):
            violations.append(
                self.violation("'plugins' must be an array", file_path=marketplace_file)
            )

        return violations


class MarketplaceRegistrationRule(Rule):
    """Check that plugins are registered in marketplace.json"""

    @property
    def rule_id(self) -> str:
        return "marketplace-registration"

    @property
    def description(self) -> str:
        return "Plugins must be registered in marketplace.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Only check if marketplace exists
        if not context.has_marketplace():
            return violations

        marketplace_file = context.root_path / ".claude-plugin" / "marketplace.json"

        for plugin_path in context.plugins:
            plugin_name = context.get_plugin_name(plugin_path)

            if not context.is_registered_in_marketplace(plugin_name):
                violations.append(
                    self.violation(
                        f"Plugin '{plugin_name}' not registered in marketplace.json",
                        file_path=marketplace_file,
                    )
                )

        return violations
