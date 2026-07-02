"""
Rule: marketplace-registration
"""

import json
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import MarketplaceConfigNode, PluginNode
from skillsaw.rules.builtin.marketplace.json_valid import is_valid_plugin_root


class MarketplaceRegistrationRule(Rule):
    """Check that plugins are registered in marketplace.json"""

    autofix_confidence = AutofixConfidence.SUGGEST

    repo_types = {RepositoryType.MARKETPLACE}

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

        config_nodes = context.lint_tree.find(MarketplaceConfigNode)
        if not config_nodes:
            return violations

        marketplace_file = config_nodes[0].path

        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_name = context.get_plugin_name(plugin_node.path)

            if not context.is_registered_in_marketplace(plugin_name):
                violations.append(
                    self.violation(
                        f"Plugin '{plugin_name}' not registered in marketplace.json",
                        file_path=marketplace_file,
                    )
                )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        if not violations:
            return results

        config_nodes = context.lint_tree.find(MarketplaceConfigNode)
        if not config_nodes:
            return results

        marketplace_file = config_nodes[0].path

        original = marketplace_file.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
        except json.JSONDecodeError:
            return results

        # marketplace-json-valid reports malformed shapes; mutating a
        # non-object document or non-list plugins would crash, so leave
        # those for manual repair.
        if not isinstance(data, dict):
            return results

        if "plugins" not in data:
            data["plugins"] = []
        if not isinstance(data["plugins"], list):
            return results

        # metadata.pluginRoot is prepended to relative sources when Claude
        # Code resolves them, so generated sources must be relative to it.
        # Absolute or traversing pluginRoots are invalid (marketplace-json-valid
        # flags them) and are ignored here. Resolve the base because
        # plugin_node.path is fully resolved and relative_to() compares
        # lexically.
        source_base = context.root_path
        metadata = data.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("pluginRoot"), str):
            plugin_root = metadata["pluginRoot"]
            if is_valid_plugin_root(plugin_root):
                source_base = (context.root_path / plugin_root).resolve()

        fixed_violations = []
        for v in violations:
            if "not registered" not in v.message:
                continue
            name_match = v.message.split("'")
            if len(name_match) < 2:
                continue
            plugin_name = name_match[1]
            if any(p.get("name") == plugin_name for p in data["plugins"] if isinstance(p, dict)):
                continue
            rel_source = plugin_name
            for plugin_node in context.lint_tree.find(PluginNode):
                if context.get_plugin_name(plugin_node.path) == plugin_name:
                    try:
                        rel_source = str(plugin_node.path.relative_to(source_base))
                    except ValueError:
                        # The plugin lives outside metadata.pluginRoot. Spec
                        # consumers resolve every relative source under
                        # pluginRoot and '..' is forbidden in sources, so no
                        # correct relative source exists — skip rather than
                        # register an entry that resolves to the wrong
                        # location.
                        rel_source = None
                    break
            if rel_source is None:
                continue
            # Relative sources must start with ./ per the marketplace spec.
            data["plugins"].append({"name": plugin_name, "source": f"./{rel_source}"})
            fixed_violations.append(v)

        if fixed_violations:
            fixed = json.dumps(data, indent=2) + "\n"
            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=marketplace_file,
                    confidence=AutofixConfidence.SUGGEST,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Registered {len(fixed_violations)} plugin(s) in marketplace.json",
                    violations_fixed=fixed_violations,
                )
            )

        return results
