"""
Rule: plugin-readme
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES


class PluginReadmeRule(Rule):
    """Check that plugin has a README.md"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-readme"

    @property
    def description(self) -> str:
        return "Plugin should have a README.md file"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_path = plugin_node.path
            readme = plugin_path / "README.md"
            if not readme.exists():
                violations.append(
                    self.violation("Missing README.md (recommended)", file_path=readme)
                )

        return violations
