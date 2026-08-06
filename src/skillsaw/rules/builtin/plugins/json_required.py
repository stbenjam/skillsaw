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
    # carry — one report per ecosystem. Two things take a plugin back out
    # of the exemption, both of them the author declaring it a Claude
    # plugin: the Claude marketplace listing it, or the directory carrying
    # a ``.claude-plugin/`` of its own (provenance reads the marker, so a
    # deleted or never-added manifest inside it is precisely the defect
    # this rule reports, with `strict: false` as the designed opt-out).
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
            plugin_path = plugin_node.path
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
            if not plugin_json.exists():
                # Check if plugin has strict: false in marketplace metadata
                resolved_path = safe_resolve(plugin_path) or plugin_path

                if resolved_path in getattr(context, "plugin_metadata", {}):
                    marketplace_entry = context.plugin_metadata[resolved_path]
                    if marketplace_entry.get("strict", True) is False:
                        # When strict: false, plugin.json is optional
                        continue

                violations.append(self.violation("Missing plugin.json", file_path=plugin_json))

        return violations
