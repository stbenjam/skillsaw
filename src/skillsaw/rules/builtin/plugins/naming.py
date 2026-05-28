"""
Rule: plugin-naming
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES


class PluginNamingRule(Rule):
    """Check that plugin follows naming conventions"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-naming"

    @property
    def description(self) -> str:
        return "Plugin names should use kebab-case"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_path = plugin_node.path
            plugin_name = context.get_plugin_name(plugin_path)

            if not self._is_kebab_case(plugin_name):
                violations.append(
                    self.violation(
                        f"Plugin name '{plugin_name}' should use kebab-case",
                        file_path=plugin_path,
                    )
                )

        return violations

    @staticmethod
    def _is_kebab_case(name: str) -> bool:
        """Check if a name follows kebab-case convention"""
        return bool(re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name))
