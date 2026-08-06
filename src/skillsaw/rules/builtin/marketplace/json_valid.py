"""
Rule: marketplace-json-valid
"""

import re
from typing import List

from skillsaw.paths import has_parent_traversal, is_absolute_path, safe_is_dir, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import MarketplaceConfigNode, PluginNode
from skillsaw.rules.builtin.utils import read_json

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def is_valid_plugin_root(plugin_root: str) -> bool:
    """True when metadata.pluginRoot is safe to compose with plugin sources:
    a non-empty relative path with no '..' components."""
    return (
        bool(plugin_root)
        and not is_absolute_path(plugin_root)
        and not has_parent_traversal(plugin_root)
    )


# Required fields for each object source type per the plugin-marketplaces
# docs; unknown types get a warning rather than an error so a new source
# type added upstream never breaks existing marketplaces.
_SOURCE_REQUIRED_FIELDS = {
    "github": ("repo",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
}


class MarketplaceJsonValidRule(Rule):
    """Check that marketplace.json is valid"""

    repo_types = {RepositoryType.MARKETPLACE}

    aliases = ("marketplace-json-valid",)

    @property
    def rule_id(self) -> str:
        return "claude-marketplace-json-valid"

    @property
    def description(self) -> str:
        return "Marketplace.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    @staticmethod
    def _has_claude_plugin(context: RepositoryContext) -> bool:
        """Whether any discovered plugin carries a ``.claude-plugin`` marker.

        The marker directory — not the manifest inside it — is the signal:
        it has no purpose other than Claude tooling, so its presence declares
        Claude intent even when ``plugin.json`` is missing (a defect that
        plugin-json-required reports on exactly the same evidence). That
        declared intent is what makes the missing Claude marketplace a real
        defect rather than an artifact of a Codex repo keeping its plugins
        where the Codex docs say to.
        """
        for node in context.lint_tree.find(PluginNode):
            plugin_root = safe_resolve(node.path)
            marker = node.path / ".claude-plugin"
            marker_root = safe_resolve(marker)
            if (
                plugin_root is not None
                and marker_root is not None
                and marker_root.is_relative_to(plugin_root)
                and safe_is_dir(marker)
            ):
                return True
        return False

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        # Only check if marketplace exists
        if RepositoryType.MARKETPLACE not in context.repo_types:
            return violations

        # plugins/* children dropped by discovery because they resolve
        # outside the repository root (an escaping symlink). The
        # containment is deliberate — autofix must never write outside
        # the checkout — but the drop must be visible in JSON/SARIF
        # output, not just the log: an entire plugin losing rule
        # coverage while the grade improves is a silent break. WARNING,
        # not the rule's ERROR default: the plugin's content is skipped,
        # not known to be defective.
        for item in getattr(context, "escaped_plugin_dirs", ()):
            violations.append(
                self.violation(
                    f"Plugin directory './plugins/{item.name}' resolves outside "
                    "the repository root and was skipped — its content is not "
                    "linted. Move the plugin inside the repository (or vendor "
                    "it) to restore coverage.",
                    file_path=item,
                    severity=Severity.WARNING,
                )
            )

        config_nodes = context.lint_tree.find(MarketplaceConfigNode)
        if not config_nodes:
            # Asked of the filesystem, not of repo_types: an explicit
            # ``--type marketplace`` drops CODEX_MARKETPLACE from the set,
            # and an exemption read from repo_types would go with it —
            # resurrecting this very false positive on a repository the
            # default invocation calls clean.
            # codex_catalog_exists() checks existence, not validity: a broken
            # catalog is still the author saying this is a Codex marketplace,
            # and codex-marketplace-json-valid reports what is wrong with it.
            if context.codex_catalog_exists() and not self._has_claude_plugin(context):
                # MARKETPLACE was inferred from a bare plugins/ directory, and
                # a Codex marketplace already explains that directory — the
                # Codex docs prescribe storing plugins under
                # $REPO_ROOT/plugins/. Demanding a Claude manifest there would
                # misclassify Codex-only marketplaces, whose catalog is handled
                # by codex-marketplace-json-valid. A repository that ships
                # a real Claude plugin alongside its Codex catalog is exempt
                # from the exemption — the author declared a Claude plugin, so
                # the Claude marketplace that would publish it is still
                # required (the same rule plugin-json-required applies).
                return violations
            violations.append(
                self.violation(
                    "Marketplace file not found",
                    file_path=context.root_path / ".claude-plugin" / "marketplace.json",
                )
            )
            return violations

        marketplace_file = config_nodes[0].path

        # Try to parse
        marketplace, error = read_json(marketplace_file)
        if error:
            violations.append(self.violation(f"Invalid JSON: {error}", file_path=marketplace_file))
            return violations

        # Validate that marketplace is a dictionary
        if not isinstance(marketplace, dict):
            violations.append(
                self.violation(
                    "Marketplace file must contain a JSON object", file_path=marketplace_file
                )
            )
            return violations

        # Validate required fields
        if "name" not in marketplace:
            violations.append(self.violation("Missing 'name' field", file_path=marketplace_file))
        elif isinstance(marketplace["name"], str) and not _KEBAB_CASE.match(marketplace["name"]):
            violations.append(
                self.violation(
                    f"Marketplace name '{marketplace['name']}' should be kebab-case "
                    "(lowercase letters, numbers, and hyphens)",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )

        if "owner" not in marketplace:
            violations.append(self.violation("Missing 'owner' field", file_path=marketplace_file))
        elif not isinstance(marketplace["owner"], dict):
            violations.append(
                self.violation("'owner' must be an object", file_path=marketplace_file)
            )
        elif "name" not in marketplace["owner"]:
            violations.append(
                self.violation("'owner' must have a 'name' field", file_path=marketplace_file)
            )

        plugin_root = None
        metadata = marketplace.get("metadata")
        if isinstance(metadata, dict) and "pluginRoot" in metadata:
            if not isinstance(metadata["pluginRoot"], str):
                violations.append(
                    self.violation(
                        "'metadata.pluginRoot' must be a string", file_path=marketplace_file
                    )
                )
            else:
                plugin_root = metadata["pluginRoot"]
                if has_parent_traversal(plugin_root):
                    violations.append(
                        self.violation(
                            "metadata.pluginRoot: path contains '..' — the plugin "
                            "root must stay within the marketplace repository",
                            file_path=marketplace_file,
                        )
                    )
                elif is_absolute_path(plugin_root):
                    violations.append(
                        self.violation(
                            f"metadata.pluginRoot: absolute path '{plugin_root}' — "
                            "the plugin root must be a relative path inside the "
                            "marketplace repository",
                            file_path=marketplace_file,
                        )
                    )

        if "plugins" not in marketplace:
            violations.append(self.violation("Missing 'plugins' array", file_path=marketplace_file))
        elif not isinstance(marketplace["plugins"], list):
            violations.append(
                self.violation("'plugins' must be an array", file_path=marketplace_file)
            )
        else:
            seen_names = {}
            for idx, entry in enumerate(marketplace["plugins"]):
                if not isinstance(entry, dict):
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] must be an object",
                            file_path=marketplace_file,
                        )
                    )
                    continue

                if "name" not in entry:
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] missing required 'name' field",
                            file_path=marketplace_file,
                        )
                    )
                elif not isinstance(entry["name"], str):
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] plugin name must be a string, "
                            f"got {entry['name']!r}",
                            file_path=marketplace_file,
                        )
                    )
                else:
                    name = entry["name"]
                    if name in seen_names:
                        violations.append(
                            self.violation(
                                f"plugins[{idx}] duplicate plugin name '{name}' "
                                f"(first defined at plugins[{seen_names[name]}])",
                                file_path=marketplace_file,
                            )
                        )
                    else:
                        seen_names[name] = idx

                if "source" not in entry:
                    violations.append(
                        self.violation(
                            f"plugins[{idx}] missing required 'source' field",
                            file_path=marketplace_file,
                        )
                    )
                else:
                    violations.extend(
                        self._check_source(entry["source"], idx, marketplace_file, plugin_root)
                    )

        return violations

    def _check_source(self, source, idx: int, marketplace_file, plugin_root) -> List[RuleViolation]:
        """Validate a plugin entry's source (relative path or typed object)."""
        violations = []

        if isinstance(source, str):
            if is_absolute_path(source):
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: absolute path '{source}' — sources "
                        "must be relative paths inside the marketplace repository",
                        file_path=marketplace_file,
                    )
                )
                return violations
            if has_parent_traversal(source):
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: path contains '..' — sources must "
                        "stay within the marketplace repository",
                        file_path=marketplace_file,
                    )
                )
            elif not source.startswith("./") and not plugin_root:
                # With metadata.pluginRoot set, bare names (e.g. "formatter")
                # are the documented form, so no style nudge applies.
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: relative path '{source}' should "
                        "start with './'",
                        file_path=marketplace_file,
                        severity=Severity.INFO,
                    )
                )
            return violations

        if not isinstance(source, dict):
            violations.append(
                self.violation(
                    f"plugins[{idx}].source must be a relative path string or an object",
                    file_path=marketplace_file,
                )
            )
            return violations

        source_type = source.get("source")
        if not isinstance(source_type, str):
            violations.append(
                self.violation(
                    f"plugins[{idx}].source object missing required 'source' type field",
                    file_path=marketplace_file,
                )
            )
            return violations

        if source_type not in _SOURCE_REQUIRED_FIELDS:
            violations.append(
                self.violation(
                    f"plugins[{idx}].source: unknown source type '{source_type}' "
                    f"(known types: {', '.join(sorted(_SOURCE_REQUIRED_FIELDS))})",
                    file_path=marketplace_file,
                    severity=Severity.WARNING,
                )
            )
            return violations

        for required in _SOURCE_REQUIRED_FIELDS[source_type]:
            if required not in source:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source of type '{source_type}' requires "
                        f"a '{required}' field",
                        file_path=marketplace_file,
                    )
                )

        return violations
