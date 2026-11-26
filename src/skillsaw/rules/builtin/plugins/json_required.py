"""
Rule: plugin-json-required
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES
from skillsaw.paths import safe_resolve


class PluginJsonRequiredRule(Rule):
    """Check that plugin.json exists"""

    repo_types = PLUGIN_REPO_TYPES

    # Codex-only plugins are exempt: they have no reason to carry a Claude
    # manifest, and codex-plugin-json-valid validates the one they do
    # carry. A ``.claude-plugin/`` that is not just a marketplace catalog
    # declares a Claude plugin, so a missing manifest inside it is reported.
    # A directory a Claude marketplace entry registers needs no manifest:
    # without plugin.json the entry is the manifest, whatever ``strict`` says.
    provenance_scope = "claude"

    aliases = ("plugin-json-required",)

    @property
    def rule_id(self) -> str:
        return "claude-plugin-json-required"

    @property
    def description(self) -> str:
        return "Plugin must have .claude-plugin/plugin.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_node in self.scoped_find(context, PluginNode):
            if context.is_project_claude_dir(plugin_node.path):
                continue  # project configuration, not a plugin
            plugin_path = plugin_node.path
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
            if plugin_json.exists():
                continue
            resolved_path = safe_resolve(plugin_path) or plugin_path
            if resolved_path in context.marketplace_entries:
                continue
            violations.append(self.violation("Missing plugin.json", file_path=plugin_json))

        return violations
