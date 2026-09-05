"""
Rule: grok-plugin-json-valid

Validates `.grok-plugin/plugin.json` manifests for Grok Build plugins.
Ensures manifests have valid JSON syntax, required plugin names, valid
semantic versions, and existing component path references.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from skillsaw.context import RepositoryContext
from skillsaw.diagnostics import safe_display
from skillsaw.formats import grok
from skillsaw.formats.grok_manifest import manifest_type_errors, read_manifest_json
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.paths import contained_resolve, safe_exists, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity

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
                "Warn when a declared skills, commands or agents path drops components "
                "the conventional directory would have loaded"
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
            data, error = read_manifest_json(manifest)
            if error:
                violations.append(self.violation(f"Invalid JSON: {error}", file_path=manifest))
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation("Plugin manifest must be a JSON object", file_path=manifest)
                )
                continue

            violations.extend(self._check_name(data, manifest))
            type_errors = manifest_type_errors(data)
            if type_errors:
                violations.extend(
                    self.violation(message, file_path=manifest) for message in type_errors
                )
                # A typed-member error rejects the whole manifest; path-loss
                # and metadata advice would describe a plugin that cannot load.
                continue
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
                target = plugin_dir / raw
                contained = contained_resolve(target, root)
                if contained is None:
                    reason = escape_reason(raw, root, "plugin root")
                    violations.append(
                        self.violation(
                            f"'{field}': '{safe_display(raw)}' {reason}",
                            file_path=manifest,
                            severity=Severity.WARNING,
                        )
                    )
                    continue
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
                resolved.append(contained)

            if check_overrides:
                violations.extend(
                    self._check_override(
                        field, resolved, manifest, plugin_dir, root, declares=bool(declared)
                    )
                )

        return violations

    def _declared_paths(self, value: Any) -> Optional[List[str]]:
        """The paths *value* declares, or ``None`` when it is the inline form.

        A bare string is as valid as an array — Grok's field is an untagged
        ``PathOrPaths`` — so neither is a finding. Directory fields have
        already passed typed validation; inline fields may hold any JSON
        value and are interpreted by their component's own consumer.
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
        declares: bool,
    ) -> List[RuleViolation]:
        """An override replaces the conventional directory, never extends it.

        Measured: ``"skills": ["custom-skills"]`` loaded the override and
        nothing from ``skills/``. The official catalog tool unions the two,
        so a plugin that validates against it still loses everything under
        the conventional directory at runtime.

        What counts as a loss is what the conventional scan would *load*,
        and the two scans have different shapes — measured against 1.0.13
        and recorded in :data:`grok.COMPONENT_PATHS`. ``skills`` is walked
        recursively, so every directory holding a ``SKILL.md`` at any depth
        loads and a declaration anywhere above one keeps it. ``commands``
        and ``agents`` are flat, so only a ``*.md`` directly inside the
        declared directory loads and only that directory covers it. A
        directory holding a README or a ``.gitkeep`` loses nothing either
        way.

        *declares* rather than a non-empty *declared*: a field whose every
        path escaped the plugin or does not exist still replaces the
        conventional directory, so the whole of it is lost and the loss is
        worth naming beside the per-path warning.
        """
        if field not in _OVERRIDE_FIELDS or not declares:
            return []
        conventional_name = grok.COMPONENT_PATHS[field][0]
        conventional = plugin_dir / conventional_name
        # Indexed, not scanned per component: a manifest is repository
        # content, so a catalog-sized declaration list beside a
        # catalog-sized conventional directory would otherwise be quadratic.
        covered = set(declared)
        recursive = field == "skills"
        dropped = sorted(
            component.name
            for component in self._conventional_components(conventional, field, root)
            if not self._covered_by(component, covered, root, recursive)
        )
        if not dropped:
            return []
        return [
            self.violation(
                f"'{field}' replaces '{conventional_name}/'; Grok stops loading "
                f"'{safe_display(dropped[0])}'",
                file_path=manifest,
                severity=Severity.WARNING,
            )
        ]

    @staticmethod
    def _covered_by(component: Path, declared: Set[Path], root: Path, recursive: bool) -> bool:
        """Whether a declared path's own scan still loads *component*.

        The flat fields need the declared directory to *be* the component's
        parent; the recursive one takes any ancestor, itself included. The
        walk up stops at the plugin root, so the cost is the component's
        depth rather than the size of the declaration list.
        """
        if not recursive:
            return component.parent in declared
        current = component
        while True:
            if current in declared:
                return True
            if current == root or current.parent == current:
                return False
            current = current.parent

    def _conventional_components(self, directory: Path, field: str, root: Path) -> List[Path]:
        """Resolved components the conventional scan would load.

        Contained before it is listed or stat'd: an override beside a
        ``skills`` symlinked out of the plugin displaces nothing Grok would
        have loaded, and listing it would read a directory outside the
        checkout.
        """
        if field != "skills":
            return [
                resolved
                for child in self._children(directory, root)
                if child.suffix == ".md"
                and (resolved := contained_resolve(child, root)) is not None
                and safe_is_file(child)
            ]
        # Recursive, and the directory itself counts: measured, ``skills/``
        # holding its own ``SKILL.md`` loads as a skill and one at
        # ``skills/a/b/c/SKILL.md`` loads too, with no pruning at the first
        # hit. Iterative, and deduplicated on the resolved directory, so a
        # symlink cycle inside the plugin cannot loop.
        found: List[Path] = []
        seen: Set[Path] = set()
        stack: List[Path] = [directory]
        while stack:
            current = stack.pop()
            resolved = contained_resolve(current, root)
            if resolved is None or resolved in seen or not safe_is_dir(current):
                continue
            seen.add(resolved)
            if safe_is_file(current / grok.SKILL_FILENAME):
                found.append(resolved)
            stack.extend(self._children(current, root))
        return found

    @staticmethod
    def _children(directory: Path, root: Path) -> List[Path]:
        """Entries of *directory*, or none when it escapes *root* or cannot be listed."""
        if contained_resolve(directory, root) is None or not safe_is_dir(directory):
            return []
        try:
            return sorted(directory.iterdir())
        except OSError:
            return []

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
