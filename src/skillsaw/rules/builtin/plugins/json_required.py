"""
Rule: plugin-json-required
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode

from ._helpers import PLUGIN_REPO_TYPES


class PluginJsonRequiredRule(Rule):
    """Check that plugin.json exists"""

    repo_types = PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "plugin-json-required"

    @property
    def description(self) -> str:
        return "Plugin must have .claude-plugin/plugin.json"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_path = plugin_node.path
            plugin_json = plugin_path / ".claude-plugin" / "plugin.json"
            if not plugin_json.exists():
                # Check if plugin has strict: false in marketplace metadata
                resolved_path = plugin_path.resolve()

                if (
                    resolved_path not in getattr(context, "marketplace_entries", {})
                    and plugin_path.joinpath(*context.CODEX_PLUGIN_MANIFEST).is_file()
                ):
                    # A Codex plugin, swept up here only because it also ships
                    # a commands/ or skills/ directory. It has no reason to
                    # carry a Claude manifest, and codex-plugin-json-valid
                    # validates the one it does carry. A plugin the Claude
                    # marketplace lists is exempt from the exemption — the
                    # author declared it a Claude plugin, so it needs the
                    # Claude manifest (and `strict: false` below is the
                    # designed opt-out).
                    continue

                if resolved_path in getattr(context, "plugin_metadata", {}):
                    marketplace_entry = context.plugin_metadata[resolved_path]
                    if marketplace_entry.get("strict", True) is False:
                        # When strict: false, plugin.json is optional
                        continue

                violations.append(self.violation("Missing plugin.json", file_path=plugin_json))

        return violations
