"""
Rule: marketplace-registration
"""

import json
from pathlib import Path
from typing import List, Optional

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import MarketplaceConfigNode, PluginNode
from skillsaw.rules.builtin.marketplace.json_valid import is_valid_plugin_root


def _mutable_marketplace_data(original: str) -> Optional[dict]:
    """Parse marketplace.json into a document ``fix()`` can extend.

    Returns the parsed dict, or ``None`` when the file cannot be rewritten
    safely — unparseable JSON, a non-object root, or a non-list ``plugins``
    key.  marketplace-json-valid reports those malformed shapes; they need
    manual repair, so registration violations against them must not
    advertise fixability.

    Shared by ``check()`` (to decide ``fixable``) and ``fix()`` so the two
    cannot drift.
    """
    try:
        data = json.loads(original)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if "plugins" in data and not isinstance(data["plugins"], list):
        return None
    return data


def _source_base(context: RepositoryContext, data: dict) -> Path:
    """Base directory that generated plugin sources are relative to.

    metadata.pluginRoot is prepended to relative sources when Claude Code
    resolves them, so generated sources must be relative to it.  Absolute
    or traversing pluginRoots are invalid (marketplace-json-valid flags
    them) and are ignored here.  Resolve the base because plugin node paths
    are fully resolved and relative_to() compares lexically.
    """
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("pluginRoot"), str):
        plugin_root = metadata["pluginRoot"]
        if is_valid_plugin_root(plugin_root):
            return (context.root_path / plugin_root).resolve()
    return context.root_path


def _relative_source(plugin_path: Path, source_base: Path) -> Optional[str]:
    """Marketplace-relative source for the plugin, or ``None`` when it lives
    outside the source base.

    Spec consumers resolve every relative source under pluginRoot and '..'
    is forbidden in sources, so no correct relative source exists for a
    plugin outside it — registering one would resolve to the wrong location.
    """
    try:
        return str(plugin_path.relative_to(source_base))
    except ValueError:
        return None


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

        unregistered = []
        for plugin_node in context.lint_tree.find(PluginNode):
            plugin_name = context.get_plugin_name(plugin_node.path)

            if not context.is_registered_in_marketplace(plugin_name):
                unregistered.append((plugin_node, plugin_name))

        if not unregistered:
            return violations

        # fix() bails on documents it cannot safely rewrite and on plugins
        # with no valid relative source under metadata.pluginRoot, so
        # fixability must be decided per violation by the same helpers fix()
        # runs — otherwise lint output over-promises `[*] fixable with
        # skillsaw fix`.
        try:
            data = _mutable_marketplace_data(marketplace_file.read_text(encoding="utf-8"))
        except OSError:
            data = None
        source_base = _source_base(context, data) if data is not None else None

        for plugin_node, plugin_name in unregistered:
            fixable = (
                data is not None and _relative_source(plugin_node.path, source_base) is not None
            )
            violations.append(
                self.violation(
                    f"Plugin '{plugin_name}' not registered in marketplace.json",
                    file_path=marketplace_file,
                    fixable=fixable,
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
        data = _mutable_marketplace_data(original)
        if data is None:
            # Malformed document (invalid JSON, non-object root, or non-list
            # plugins) — reported by marketplace-json-valid, left for manual
            # repair.  check() marks these violations fixable=False.
            return results

        if "plugins" not in data:
            data["plugins"] = []

        source_base = _source_base(context, data)

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
                    # None means the plugin lives outside metadata.pluginRoot;
                    # skip rather than register an entry that resolves to the
                    # wrong location.  check() marks it fixable=False.
                    rel_source = _relative_source(plugin_node.path, source_base)
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
