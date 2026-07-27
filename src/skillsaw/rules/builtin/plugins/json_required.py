"""
Rule: plugin-json-required
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.formats.codex import codex_manifest_is_contained
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

                # Asked of the filesystem, not of discovery: an explicit
                # ``--type`` override switches Codex discovery off, and an
                # exemption read from it would vanish under
                # ``--type marketplace`` — same repository, contradictory
                # answers. ``codex_manifest_is_contained`` applies the same
                # containment discovery does, so a manifest symlinked out of
                # the plugin still exempts nothing.
                if (
                    resolved_path not in getattr(context, "marketplace_entries", {})
                    and not (plugin_path / ".claude-plugin").is_dir()
                    # The filesystem probe survives a ``--type`` override
                    # that switches Codex discovery off; the claim check
                    # additionally covers a directory a catalog lists but
                    # that ships no manifest yet — codex-plugin-json-valid
                    # owns that defect, one report per ecosystem.
                    and (
                        codex_manifest_is_contained(plugin_path)
                        or context.is_codex_claimed(plugin_path)
                    )
                ):
                    # A Codex plugin, swept up here only because it also ships
                    # a commands/ or skills/ directory. It has no reason to
                    # carry a Claude manifest, and codex-plugin-json-valid
                    # validates the one it does carry. Two things take a
                    # plugin back out of the exemption, both of them the
                    # author declaring it a Claude plugin: the Claude
                    # marketplace listing it, or the directory carrying a
                    # ``.claude-plugin/`` of its own. In the second case the
                    # manifest inside it was deleted or never added, and that
                    # is precisely the defect this rule reports (with
                    # `strict: false` below as the designed opt-out).
                    continue

                if resolved_path in getattr(context, "plugin_metadata", {}):
                    marketplace_entry = context.plugin_metadata[resolved_path]
                    if marketplace_entry.get("strict", True) is False:
                        # When strict: false, plugin.json is optional
                        continue

                violations.append(self.violation("Missing plugin.json", file_path=plugin_json))

        return violations
