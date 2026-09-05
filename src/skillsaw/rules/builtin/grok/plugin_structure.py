"""
Rule: grok-plugin-structure

Checks that a Grok Build plugin directory contains either a manifest or
recognized installable components (`skills/`, `agents/`, `hooks/hooks.json`,
or `.mcp.json`).
"""

from pathlib import Path
from typing import List, Set

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.formats.grok_manifest import manifest_type_errors, read_manifest_json
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.paths import (
    contained_resolve,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import GROK_PLUGIN_REPO_TYPES

#: What ``grok plugin install`` accepts from a manifest-less directory,
#: rendered for the one message this rule has.
_INSTALLABLE = "skills/, agents/, hooks/hooks.json or .mcp.json"


class GrokPluginStructureRule(Rule):
    """Check that a Grok Build plugin directory holds something Grok installs"""

    since = "0.20.0"

    repo_types = GROK_PLUGIN_REPO_TYPES

    config_schema = {
        "check-installable": {
            "type": "bool",
            "default": True,
            "description": (
                "Warn when a plugin directory holds neither a manifest nor a component "
                "'grok plugin install' accepts"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "grok-plugin-structure"

    @property
    def description(self) -> str:
        return "A Grok plugin directory needs a manifest or a component Grok installs"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        check_installable = self.setting("check-installable")
        # One enumeration for the whole run: a catalog addressing the
        # directory by name is what makes a synthesized install name a
        # problem rather than a detail.
        addressed: Set[Path] = set(context.grok_local_source_dirs())

        for node in context.lint_tree.find(GrokPluginConfigNode):
            plugin_dir = node.plugin_dir
            if not safe_is_dir(plugin_dir):
                # A catalog source that does not resolve. One defect, and it
                # belongs to grok-marketplace-json-valid, which names the
                # entry that declared it.
                continue
            if safe_is_file(node.path):
                continue
            if not self._installable(plugin_dir):
                if self._has_child_plugin(plugin_dir):
                    # The installer selects children, not a synthesized parent.
                    continue
                if not check_installable:
                    # The naming advisory below still applies: a directory
                    # whose components are generated at build time installs
                    # under a synthesized name all the same.
                    violations.extend(self._synthesized_name(plugin_dir, addressed))
                    continue
                violations.append(
                    self.violation(
                        f"Grok installs nothing from '{plugin_dir.name}/': no "
                        f"{grok.PLUGIN_DIR_NAME}/{grok.PLUGIN_MANIFEST} and none of "
                        f"{_INSTALLABLE}, and no installable immediate child plugin",
                        file_path=plugin_dir,
                    )
                )
                continue
            violations.extend(self._synthesized_name(plugin_dir, addressed))

        return violations

    def _synthesized_name(self, plugin_dir: Path, addressed: Set[Path]) -> List[RuleViolation]:
        """The name a manifest-less directory installs under, when a catalog
        asks for another one."""
        resolved = safe_resolve(plugin_dir)
        if resolved is None or resolved not in addressed:
            return []
        return [
            self.violation(
                f"'{plugin_dir.name}/' has no manifest; Grok installs it as "
                f"'{plugin_dir.name}-<hash>', not under the catalog's name",
                file_path=plugin_dir,
                severity=Severity.INFO,
            )
        ]

    def _installable(self, plugin_dir: Path) -> bool:
        """Whether ``grok plugin install`` accepts *plugin_dir* with no manifest.

        Every candidate is contained against the plugin first: Grok drops a
        component that resolves outside the plugin root, so one that does
        cannot make the directory installable, and counting it would call a
        directory fine that the installer refuses.
        """
        root = safe_resolve(plugin_dir)
        if root is None:
            return False
        for field in ("skills", "agents"):
            directory = plugin_dir / grok.COMPONENT_PATHS[field][0]
            if contained_resolve(directory, root) is not None and safe_is_dir(directory):
                # Installation tests directory presence, not content depth.
                return True
        for field in ("hooks", "mcpServers"):
            if _contained_file(plugin_dir / grok.COMPONENT_PATHS[field][0], root):
                return True
        return False

    def _has_child_plugin(self, plugin_dir: Path) -> bool:
        """The installer's one-level fallback, without following child symlinks."""
        root = safe_resolve(plugin_dir)
        if root is None:
            return False
        for child in _children(plugin_dir, root):
            if (
                safe_is_symlink(child)
                or not safe_is_dir(child)
                or contained_resolve(child, root) is None
            ):
                continue
            if self._installable(child):
                return True
            manifest = grok.grok_manifest_path(child)
            if manifest is None:
                continue
            data, error = read_manifest_json(manifest)
            if error or not isinstance(data, dict) or manifest_type_errors(data):
                continue
            name = data.get("name")
            if isinstance(name, str) and grok.PLUGIN_NAME_RE.fullmatch(name):
                return True
        return False


def _contained_file(path: Path, root: Path) -> bool:
    """Whether *path* is a regular file that stays inside *root*."""
    return contained_resolve(path, root) is not None and safe_is_file(path)


def _children(directory: Path, root: Path) -> List[Path]:
    """Entries of *directory*, or none when it cannot be listed or escapes."""
    if contained_resolve(directory, root) is None:
        return []
    try:
        return list(directory.iterdir())
    except OSError:
        return []
