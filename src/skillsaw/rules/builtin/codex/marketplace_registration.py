"""Rule: codex-marketplace-registration."""

from typing import List

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexMarketplaceConfigNode, CodexPluginNode
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import CODEX_MARKETPLACE_REPO_TYPES


class CodexMarketplaceRegistrationRule(Rule):
    """Require locally discovered Codex plugins to be cataloged."""

    repo_types = CODEX_MARKETPLACE_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "codex-marketplace-registration"

    @property
    def description(self) -> str:
        return "Local Codex plugins must be registered in marketplace.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        nodes = context.lint_tree.find(CodexMarketplaceConfigNode)
        if not nodes or not isinstance(context.codex_marketplace_data, dict):
            return []

        marketplace_file = nodes[0].path
        violations = []
        for plugin_node in context.lint_tree.find(CodexPluginNode):
            plugin_name = context.get_codex_plugin_name(plugin_node.path)
            if not context.is_registered_in_codex_marketplace(plugin_name):
                violations.append(
                    self.violation(
                        f"Codex plugin '{plugin_name}' not registered in marketplace.json",
                        file_path=marketplace_file,
                    )
                )
        return violations
