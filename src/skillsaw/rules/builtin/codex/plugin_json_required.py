"""Rule: codex-plugin-json-required."""

from typing import List

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import CodexPluginNode
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import CODEX_PLUGIN_REPO_TYPES


class CodexPluginJsonRequiredRule(Rule):
    """Require the Codex plugin entry-point manifest."""

    repo_types = CODEX_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "codex-plugin-json-required"

    @property
    def description(self) -> str:
        return "Codex plugins must have .codex-plugin/plugin.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for plugin_node in context.lint_tree.find(CodexPluginNode):
            manifest = plugin_node.path / ".codex-plugin" / "plugin.json"
            if not manifest.is_file():
                violations.append(self.violation("Missing plugin.json", file_path=manifest))
        return violations
