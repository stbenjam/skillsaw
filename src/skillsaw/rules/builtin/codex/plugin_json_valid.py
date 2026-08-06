"""
Rule: codex-plugin-json-valid
"""

from pathlib import Path
from typing import Any, List, Tuple

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.lint_target import CodexPluginConfigNode
from skillsaw.paths import safe_exists, safe_is_dir, safe_is_file
from skillsaw.rules.builtin.utils import read_json

from ._helpers import (
    CODEX_PLUGIN_REPO_TYPES,
    KEBAB_CASE,
    nonfinite_constant_error,
    path_problem,
)

# Manifest fields that point at bundled components or assets. Every one of
# them is documented as "relative to the plugin root", starting with "./".
# ``hooks`` is excluded — it alone accepts inline objects as well as paths,
# so it is unpacked separately.
_PATH_FIELDS = ("skills", "mcpServers", "apps")
# All three are documented in plugin-json-spec.md, which also requires every
# asset path to point at a real file inside the plugin.
_INTERFACE_PATH_FIELDS = ("composerIcon", "logo", "logoDark")
_INTERFACE_PATH_LIST_FIELDS = ("screenshots",)

# What each field has to be on disk for the lint tree to follow it. Only
# fields the tree actually filters on are listed — nothing drops ``apps``
# or the ``interface`` assets silently.
_EXPECTED_KIND = {"hooks": "file", "mcpServers": "file", "skills": "dir"}


class CodexPluginJsonValidRule(Rule):
    """Check that .codex-plugin/plugin.json is valid"""

    repo_types = CODEX_PLUGIN_REPO_TYPES
    since = "0.18.0"

    DEFAULT_RECOMMENDED_FIELDS = ["version", "description"]
    config_schema = {
        "recommended-fields": {
            "type": "list",
            "default": DEFAULT_RECOMMENDED_FIELDS,
            "description": "Fields that trigger a warning if missing from plugin.json",
        },
        "check-paths-exist": {
            "type": "bool",
            "default": True,
            "description": (
                "Warn when a manifest path (skills, hooks, assets, ...) "
                "points at a file or directory that is not in the repository"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "codex-plugin-json-valid"

    @property
    def description(self) -> str:
        return ".codex-plugin/plugin.json must be valid JSON with required fields"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        recommended_fields = self.config.get("recommended-fields", self.DEFAULT_RECOMMENDED_FIELDS)
        if not isinstance(recommended_fields, (list, tuple, set)):
            # Config loading does not enforce config_schema types; a scalar
            # here would crash the rule for every manifest.
            recommended_fields = self.DEFAULT_RECOMMENDED_FIELDS
        check_paths_exist = self.config.get("check-paths-exist", True)

        for node in context.lint_tree.find(CodexPluginConfigNode):
            if context.is_codex_installed_plugin(node.plugin_dir):
                # Third-party content a developer installed. Its hooks and
                # MCP servers are still linted — they execute here — but a
                # naming or description defect in a manifest the developer
                # cannot edit is not this checkout's problem.
                continue
            manifest = node.path
            if not safe_is_file(manifest):
                # The node exists because ``.codex-plugin/`` does or because
                # a catalog claims the directory; either way Codex loads
                # nothing without the manifest at this exact path.
                violations.append(
                    self.violation(
                        "Missing .codex-plugin/plugin.json — Codex reads the "
                        "plugin manifest from this path",
                        file_path=manifest,
                    )
                )
                continue
            data, error = read_json(manifest)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=manifest))
                continue
            strict_error = nonfinite_constant_error(manifest)
            if strict_error:
                violations.append(
                    self.violation(f"Invalid JSON: {strict_error}", file_path=manifest)
                )
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Expected JSON object in plugin.json", file_path=manifest)
                )
                continue

            violations.extend(self._check_name(data, manifest))

            for field in recommended_fields:
                if not isinstance(field, str):
                    # ``field not in data`` raises TypeError on an
                    # unhashable value — a rule crash for every manifest.
                    continue
                if field not in data:
                    violations.append(
                        self.violation(
                            f"Missing recommended field '{field}'",
                            file_path=manifest,
                            severity=Severity.WARNING,
                        )
                    )

            author = data.get("author")
            if author is not None and not isinstance(author, (str, dict)):
                violations.append(
                    self.violation(
                        "'author' must be a string or an object with 'name', " "'email' and 'url'",
                        file_path=manifest,
                    )
                )

            # A non-object ``interface`` carries no displayName, category or
            # asset paths, so every check below silently skips it and the
            # plugin renders with none of its published identity.
            interface = data.get("interface")
            if interface is not None and not isinstance(interface, dict):
                violations.append(
                    self.violation(
                        "'interface' must be an object",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )

            violations.extend(self._check_paths(data, manifest, node.plugin_dir, check_paths_exist))

        return violations

    def _check_name(self, data: dict, manifest: Path) -> List[RuleViolation]:
        if "name" not in data:
            return [self.violation("Missing required field 'name'", file_path=manifest)]
        name = data["name"]
        if not isinstance(name, str):
            return [
                self.violation(
                    f"Plugin name must be a string, got '{safe_display(name)}'", file_path=manifest
                )
            ]
        if not name:
            # An empty identifier is a missing one: it belongs with the
            # required-field errors, not the kebab-case warning a default
            # ``fail-on: error`` would let pass.
            return [self.violation("Required field 'name' is an empty string", file_path=manifest)]
        if not KEBAB_CASE.match(name):
            return [
                self.violation(
                    f"Plugin name '{safe_display(name)}' should use kebab-case — plugin hosts "
                    "use it as the plugin identifier and component namespace",
                    file_path=manifest,
                    severity=Severity.WARNING,
                )
            ]
        return []

    def _check_paths(
        self, data: dict, manifest: Path, plugin_dir: Path, check_exists: bool
    ) -> List[RuleViolation]:
        """Validate every manifest field that names a bundled path."""
        violations: List[RuleViolation] = []

        for field, value in self._iter_path_values(data):
            if not isinstance(value, str):
                # ``mcpServers`` is documented as "string or object", so an
                # inline object is conformant (and already routed to the MCP
                # rules). Base name, not exact label: an array element
                # arrives as ``mcpServers[1]``.
                if field.split("[", 1)[0] == "mcpServers" and isinstance(value, dict):
                    continue
                # A warning, not an error: ``skills`` is typed as a string
                # alone, but real plugins ship arrays and Codex mirrors
                # Claude Code's loader.
                violations.append(
                    self.violation(
                        f"'{field}' is documented as a path string relative to "
                        f"the plugin root, got {type(value).__name__}",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )
                continue
            if not value:
                # "" resolves to the plugin root, so the existence check
                # below would pass and the field would look fine.
                violations.append(self.violation(f"'{field}' is an empty path", file_path=manifest))
                continue
            problem = path_problem(value, "plugin root", plugin_dir)
            if problem:
                violations.append(self.violation(f"'{field}': {problem}", file_path=manifest))
                continue
            if not value.startswith("./"):
                violations.append(
                    self.violation(
                        f"'{field}': path '{safe_display(value)}' should start with './'",
                        file_path=manifest,
                        severity=Severity.INFO,
                    )
                )
            target = plugin_dir / value
            exists = safe_exists(target)
            if check_exists and not exists:
                violations.append(
                    self.violation(
                        f"'{field}': '{safe_display(value)}' does not exist in the plugin",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )
                continue
            # Existing is not the same as usable. The lint tree follows
            # ``hooks`` and ``mcpServers`` with is_file() and ``skills``
            # with is_dir(), so a declaration of the wrong kind is dropped
            # there — silently, unless it is reported right here.
            wanted = _EXPECTED_KIND.get(field.split("[")[0])
            if wanted is None or not exists:
                continue
            if wanted == "file" and not safe_is_file(target):
                violations.append(
                    self.violation(
                        f"'{field}': '{safe_display(value)}' is a directory — this field names a file",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )
            elif wanted == "dir" and not safe_is_dir(target):
                violations.append(
                    self.violation(
                        f"'{field}': '{safe_display(value)}' is a file — this field names a directory",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )

        return violations

    def _iter_path_values(self, data: dict) -> List[Tuple[str, Any]]:
        """(field label, raw value) for every path-valued manifest field.

        Arrays are flattened to one entry per element, so an array-valued
        ``skills`` or a ``hooks`` list of paths is checked element by
        element. Inline ``hooks`` objects are skipped: the field accepts "a
        single path, an array of paths, an inline hooks object, or an array
        of inline hooks objects", and only the path forms name a file.
        """
        found: List[Tuple[str, Any]] = []

        def _flatten(label: str, value: Any, *, drop_objects: bool, depth: int = 0) -> None:
            if isinstance(value, list):
                if depth:
                    # Only one array level is permitted. Recursing further
                    # would validate the inner string as an ordinary path
                    # while discovery, which inspects one level, drops it —
                    # so an executable hook file would pass every check and
                    # still never reach the hook rules.
                    found.append((label, value))
                    return
                for idx, item in enumerate(value):
                    _flatten(f"{label}[{idx}]", item, drop_objects=drop_objects, depth=depth + 1)
                return
            if drop_objects and isinstance(value, dict):
                return
            found.append((label, value))

        for field in _PATH_FIELDS:
            if field in data:
                _flatten(field, data[field], drop_objects=False)

        if "hooks" in data:
            _flatten("hooks", data["hooks"], drop_objects=True)

        interface = data.get("interface")
        if isinstance(interface, dict):
            for field in _INTERFACE_PATH_FIELDS + _INTERFACE_PATH_LIST_FIELDS:
                if field in interface:
                    _flatten(f"interface.{field}", interface[field], drop_objects=False)

        return found
