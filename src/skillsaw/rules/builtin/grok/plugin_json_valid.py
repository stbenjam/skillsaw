"""
Rule: grok-plugin-json-valid

The shape of a Grok Build plugin manifest, and severity that carries what
each defect costs. A manifest that fails to load takes the whole plugin
directory with it — the conventional ``skills/`` does not rescue it — while
a declared path that escapes or does not exist costs that component list
alone. Both are silent: ``grok plugin install`` prints success for a plugin
``grok inspect`` then shows nothing from.

Only :class:`GrokPluginConfigNode` is iterated, a node type only Grok
populates, so the rule declares no ``provenance_scope``: the node is already
the scope.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import strict_json

from ._helpers import GROK_PLUGIN_REPO_TYPES, escape_reason, is_semver

#: Manifest keys that name a component location. ``hooks`` and ``mcpServers``
#: are ``path | inline``, so an object under either is the component itself
#: and not a path at all; the three directory fields are ``path | [path]``.
_PATH_FIELDS = ("skills", "commands", "agents", "hooks", "mcpServers")

#: The three fields whose declaration *replaces* the conventional directory
#: rather than extending it, which is what makes an override worth a finding.
_OVERRIDE_FIELDS = ("skills", "commands", "agents")


class GrokPluginJsonValidRule(Rule):
    """Validate a Grok Build plugin manifest"""

    since = "0.20.0"

    # ``enabled: auto`` on the base default. A marketplace carries the
    # plugins it catalogs, so its type activates the rule too.
    repo_types = GROK_PLUGIN_REPO_TYPES

    config_schema = {
        "check-paths-exist": {
            "type": "bool",
            "default": True,
            "description": (
                "Warn when a manifest path (skills, commands, agents, hooks, "
                "mcpServers) names something the plugin does not contain"
            ),
        },
        "check-overrides": {
            "type": "bool",
            "default": True,
            "description": (
                "Warn when a declared skills, commands or agents path replaces a "
                "populated conventional directory"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "grok-plugin-json-valid"

    @property
    def description(self) -> str:
        return ".grok-plugin/plugin.json must be valid JSON with a name Grok's loader accepts"

    def default_severity(self) -> Severity:
        # Discovery skips the whole plugin directory over either defect this
        # severity covers, and says nothing: install reports success, and
        # ``grok inspect`` reports no plugin.
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        check_paths_exist = self.setting("check-paths-exist")
        check_overrides = self.setting("check-overrides")

        for node in context.lint_tree.find(GrokPluginConfigNode):
            manifest = node.path
            if not safe_is_file(manifest):
                # A manifest is optional to Grok: a directory holding
                # skills/, agents/, hooks/hooks.json or .mcp.json installs
                # without one. What that costs is grok-plugin-structure's.
                continue
            data, error = strict_json(manifest)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=manifest))
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Plugin manifest must be a JSON object", file_path=manifest)
                )
                continue

            violations.extend(self._check_name(data, manifest))
            violations.extend(
                self._check_components(
                    data, manifest, node.plugin_dir, check_paths_exist, check_overrides
                )
            )
            violations.extend(self._check_metadata(data, manifest))

        return violations

    def _check_name(self, data: Dict[str, Any], manifest: Path) -> List[RuleViolation]:
        """``name`` is what Grok registers the plugin under, or refuses it for."""
        if "name" not in data:
            return [self.violation("Missing required field 'name'", file_path=manifest)]
        name = data["name"]
        if not isinstance(name, str):
            return [
                self.violation(
                    f"'name' must be a string, got '{safe_display(name)}'", file_path=manifest
                )
            ]
        if not name:
            return [self.violation("Required field 'name' is an empty string", file_path=manifest)]
        if not grok.PLUGIN_NAME_RE.fullmatch(name):
            return [
                self.violation(
                    f"Plugin name '{safe_display(name)}' must be 1-{grok.PLUGIN_NAME_MAX_LENGTH} "
                    "chars, lowercase alphanumeric and hyphens, no leading or trailing hyphen",
                    file_path=manifest,
                )
            ]
        return []

    def _check_components(
        self,
        data: Dict[str, Any],
        manifest: Path,
        plugin_dir: Path,
        check_paths_exist: bool,
        check_overrides: bool,
    ) -> List[RuleViolation]:
        """Declared component paths, and what an override costs.

        Warnings throughout, and deliberately not the rule's severity: the
        plugin still loads and its other components still work. What is lost
        is whatever the field named.
        """
        violations: List[RuleViolation] = []
        root = safe_resolve(plugin_dir)
        if root is None:
            return violations

        for field in _PATH_FIELDS:
            if field not in data:
                continue
            if field in grok.SINGLE_PATH_FIELDS and isinstance(data[field], list):
                # ``hooks`` and ``mcpServers`` are one path or one inline
                # object, never an array: measured, a list-valued ``hooks``
                # loaded as an empty inline document and a list-valued
                # ``mcpServers`` loaded no servers at all.
                violations.append(
                    self.violation(
                        f"'{field}' is an array; Grok reads one path or one inline object",
                        file_path=manifest,
                        severity=Severity.WARNING,
                    )
                )
                continue
            declared = self._declared_paths(data[field])
            if declared is None:
                # An inline hooks or mcpServers object: the component
                # itself, which the hooks and MCP rules read from the tree.
                continue
            want_dir = grok.COMPONENT_PATHS[field][1]
            resolved: List[Path] = []
            for raw in declared:
                if not raw:
                    violations.append(
                        self.violation(
                            f"'{field}' declares an empty path",
                            file_path=manifest,
                            severity=Severity.WARNING,
                        )
                    )
                    continue
                reason = escape_reason(raw, root, "plugin root")
                if reason:
                    violations.append(
                        self.violation(
                            f"'{field}': '{safe_display(raw)}' {reason}",
                            file_path=manifest,
                            severity=Severity.WARNING,
                        )
                    )
                    continue
                target = plugin_dir / raw
                if not safe_exists(target):
                    if check_paths_exist:
                        violations.append(
                            self.violation(
                                f"'{field}': '{safe_display(raw)}' is not in the plugin",
                                file_path=manifest,
                                severity=Severity.WARNING,
                            )
                        )
                    continue
                if not (safe_is_dir(target) if want_dir else safe_is_file(target)):
                    # Discovery reads the three component fields as
                    # directories and the two file fields as files, so a
                    # path of the other kind costs exactly what a missing
                    # one does.
                    violations.append(
                        self.violation(
                            f"'{field}': '{safe_display(raw)}' is not a "
                            f"{'directory' if want_dir else 'file'}",
                            file_path=manifest,
                            severity=Severity.WARNING,
                        )
                    )
                    continue
                contained = contained_resolve(target, root)
                if contained is not None:
                    resolved.append(contained)

            if check_overrides:
                violations.extend(self._check_override(field, resolved, manifest, plugin_dir, root))

        return violations

    def _declared_paths(self, value: Any) -> Optional[List[str]]:
        """The paths *value* declares, or ``None`` when it is the inline form.

        A bare string is as valid as an array — Grok's field is an untagged
        ``PathOrPaths`` — so neither is a finding. A non-string element is
        left alone: nothing measured says what the loader does with one, and
        guessing would report a defect that may not exist.
        """
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return None

    def _check_override(
        self,
        field: str,
        declared: List[Path],
        manifest: Path,
        plugin_dir: Path,
        root: Path,
    ) -> List[RuleViolation]:
        """An override replaces the conventional directory, never extends it.

        Measured: ``"skills": ["custom-skills"]`` loaded the override and
        nothing from ``skills/``. The official catalog tool unions the two,
        so a plugin that validates against it still loses everything under
        the conventional directory at runtime.
        """
        if field not in _OVERRIDE_FIELDS or not declared:
            return []
        conventional_name = grok.COMPONENT_PATHS[field][0]
        conventional = plugin_dir / conventional_name
        if not safe_is_dir(conventional):
            return []
        resolved_conventional = contained_resolve(conventional, root)
        if resolved_conventional is not None and resolved_conventional in declared:
            return []
        try:
            populated = any(True for _ in conventional.iterdir())
        except OSError:
            return []
        if not populated:
            return []
        return [
            self.violation(
                f"'{field}' replaces '{conventional_name}/'; Grok loads nothing under it",
                file_path=manifest,
                severity=Severity.WARNING,
            )
        ]

    def _check_metadata(self, data: Dict[str, Any], manifest: Path) -> List[RuleViolation]:
        """Metadata the marketplace browser shows. Nothing here stops a load."""
        violations: List[RuleViolation] = []
        version = data.get("version")
        if isinstance(version, str) and version and not is_semver(version):
            violations.append(
                self.violation(
                    f"'version' '{safe_display(version)}' is not a semantic version",
                    file_path=manifest,
                    severity=Severity.INFO,
                )
            )
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            violations.append(
                self.violation("Missing 'description'", file_path=manifest, severity=Severity.INFO)
            )
        return violations
