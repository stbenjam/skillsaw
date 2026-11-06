"""
Rule: marketplace-json-valid
"""

import re
from typing import List

from skillsaw.paths import has_parent_traversal, is_absolute_path, safe_is_dir, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import MarketplaceConfigNode, PluginNode
from skillsaw.rules.builtin.hooks.dangerous import dangerous_command_descriptions
from skillsaw.diagnostics import safe_display
from skillsaw.rules.builtin.utils import read_json

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Each part of a plugin id (`plugin@marketplace`) Claude Code can install:
# ASCII letters, digits, '.', '_' and '-', starting with a letter or digit.
# `claude plugin validate` fails a marketplace or entry name outside it.
_PLUGIN_ID_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_NAME_CHARS_HINT = "use only letters, digits, '.', '_', and '-', and start with a letter or digit"


def is_valid_plugin_root(plugin_root: str) -> bool:
    """True when metadata.pluginRoot is safe to compose with plugin sources:
    a non-empty relative path with no '..' components."""
    return (
        bool(plugin_root)
        and not is_absolute_path(plugin_root)
        and not has_parent_traversal(plugin_root)
    )


def _is_installable_local_source(source: str, plugin_root) -> bool:
    """Whether Claude Code installs a relative string source as written.

    Measured against ``claude plugin install`` 2.1.319: ``.`` and
    ``./``-prefixed paths install; a bare directory name installs only
    when ``metadata.pluginRoot`` is set; any other relative path, such as
    ``plugins/foo``, is refused.
    """
    if source == "." or source.startswith("./"):
        return True
    return bool(plugin_root) and bool(source) and "/" not in source and "\\" not in source


# Required fields for each object source type per the plugin-marketplaces
# docs; unknown types get a warning rather than an error so a new source
# type added upstream never breaks existing marketplaces.
_SOURCE_REQUIRED_FIELDS = {
    "github": ("repo",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
    "npm": ("package",),
    # Zip archive downloaded over HTTPS; `sha256` is optional. Claude Code
    # v2.1.224 or later is required to install one.
    "archive": ("url",),
    # Shell command that prints the plugin directory. Claude Code runs it
    # once per session after the user accepts the exact string.
    "command": ("command",),
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
            # A Grok catalog says the same thing about the same ``plugins/``
            # directory — a Grok-only marketplace is not a Claude one with a
            # missing manifest. Both are asked of the repository root only:
            # a catalog in a monorepo package explains that package's
            # ``plugins/``, and letting it stand the check down here would
            # silence the root's missing manifest.
            if (
                context.codex_catalog_exists() or context.grok_root_catalog_exists()
            ) and not self._has_claude_plugin(context):
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
        elif isinstance(marketplace["name"], str):
            name = marketplace["name"]
            if not _PLUGIN_ID_PART.fullmatch(name) or ".." in name:
                violations.append(
                    self.violation(
                        f"Marketplace name '{safe_display(name)}' cannot be installed by "
                        f"Claude Code: {_NAME_CHARS_HINT}, and do not use '..'",
                        file_path=marketplace_file,
                    )
                )
            elif not _KEBAB_CASE.match(name):
                violations.append(
                    self.violation(
                        f"Marketplace name '{safe_display(name)}' should be kebab-case "
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
                                f"plugins[{idx}] duplicate plugin name '{safe_display(name)}' "
                                f"(first defined at plugins[{seen_names[name]}])",
                                file_path=marketplace_file,
                            )
                        )
                    else:
                        seen_names[name] = idx
                    if not _PLUGIN_ID_PART.fullmatch(name):
                        violations.append(
                            self.violation(
                                f"plugins[{idx}] plugin name '{safe_display(name)}' cannot be installed "
                                f"by Claude Code: {_NAME_CHARS_HINT}",
                                file_path=marketplace_file,
                            )
                        )

                hooks = entry.get("hooks")
                if isinstance(hooks, (str, list)):
                    form = "a file path" if isinstance(hooks, str) else "an array"
                    violations.append(
                        self.violation(
                            f"plugins[{idx}].hooks is {form}, which Claude Code does not "
                            "support in a marketplace entry: the plugin fails to load. "
                            "Write 'hooks' as an inline object, or move the hooks into "
                            "the plugin's own hooks/hooks.json",
                            file_path=marketplace_file,
                        )
                    )

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
            elif not _is_installable_local_source(source, plugin_root):
                # Claude Code's marketplace schema refuses the entry at
                # install time ("must start with './'"), so only that entry
                # fails to install while the rest of the catalog loads.
                bare_name = bool(source) and "/" not in source and "\\" not in source
                shown = safe_display(source)
                problem = (
                    f"bare name '{shown}' needs metadata.pluginRoot"
                    if bare_name
                    else f"relative path '{shown}' must start with './'"
                )
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source: {problem} — Claude Code refuses to "
                        "install this plugin",
                        file_path=marketplace_file,
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

        if source_type == "command":
            violations.extend(self._check_command_source(source, idx, marketplace_file))

        return violations

    def _check_command_source(self, source, idx: int, marketplace_file) -> List[RuleViolation]:
        """Validate the shell-executing command source shape and payload."""
        violations = []
        command = source.get("command")
        command_valid = True
        # Guard on key presence, not value presence — a null command must
        # reach the type check below instead of silently skipping validation.
        if "command" in source:
            if not isinstance(command, str):
                command_valid = False
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source command must be a string",
                        file_path=marketplace_file,
                    )
                )
            elif not command.strip():
                # Whitespace-only is empty as far as a shell is concerned.
                command_valid = False
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source command must not be empty",
                        file_path=marketplace_file,
                    )
                )
            elif len(command) > 500:
                command_valid = False
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source command must be at most 500 characters",
                        file_path=marketplace_file,
                    )
                )
            elif not command.isascii() or not command.isprintable():
                command_valid = False
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source command must contain printable ASCII only",
                        file_path=marketplace_file,
                    )
                )
            elif "    " in command:
                command_valid = False
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source command must not contain four consecutive spaces",
                        file_path=marketplace_file,
                    )
                )

            if command_valid:
                for description in dangerous_command_descriptions(command):
                    violations.append(
                        self.violation(
                            f"plugins[{idx}].source command {description}",
                            file_path=marketplace_file,
                        )
                    )

        if "timeout" in source:
            timeout = source["timeout"]
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source timeout must be a whole number from 1 to 600",
                        file_path=marketplace_file,
                    )
                )

        if "mode" in source:
            mode = source["mode"]
            if not isinstance(mode, str) or mode not in {"copy", "link"}:
                violations.append(
                    self.violation(
                        f"plugins[{idx}].source mode must be 'copy' or 'link'",
                        file_path=marketplace_file,
                    )
                )

        return violations
