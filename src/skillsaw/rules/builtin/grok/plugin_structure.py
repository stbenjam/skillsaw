"""
Rule: grok-plugin-structure

Whether Grok would install anything from a plugin directory at all. A
manifest is optional — a directory holding ``skills/``, ``agents/``,
``hooks/hooks.json`` or ``.mcp.json`` installs without one — but a directory
with neither is skipped at discovery, and ``grok plugin validate`` prints
the same sentence for it as for a plugin with everything.

Measured correction to the documented component list: ``commands/`` alone
and ``.lsp.json`` alone are discovered and then refused by ``grok plugin
install`` ("no plugins found in the source"), so neither makes a directory
installable.

Only :class:`GrokPluginConfigNode` is iterated, a node type only Grok
populates, so the rule declares no ``provenance_scope``.
"""

from pathlib import Path
from typing import List, Set

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.paths import safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import GROK_PLUGIN_REPO_TYPES

#: What ``grok plugin install`` accepts from a manifest-less directory,
#: rendered for the one message this rule has.
_INSTALLABLE = "skills/<name>/SKILL.md, agents/*.md, hooks/hooks.json or .mcp.json"


class GrokPluginStructureRule(Rule):
    """Check that a Grok Build plugin directory holds something Grok installs"""

    since = "0.20.0"

    repo_types = GROK_PLUGIN_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "grok-plugin-structure"

    @property
    def description(self) -> str:
        return "A Grok plugin directory needs a manifest or a component Grok installs"

    def default_severity(self) -> Severity:
        # The repository still lints and every other plugin still installs;
        # what is lost is this one directory, with no diagnostic.
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
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
                violations.append(
                    self.violation(
                        f"Grok installs nothing from '{plugin_dir.name}/': no "
                        f"{grok.PLUGIN_DIR_NAME}/{grok.PLUGIN_MANIFEST} and none of "
                        f"{_INSTALLABLE}",
                        file_path=plugin_dir,
                    )
                )
                continue
            resolved = safe_resolve(plugin_dir)
            if resolved is not None and resolved in addressed:
                violations.append(
                    self.violation(
                        f"'{plugin_dir.name}/' has no manifest; Grok installs it as "
                        f"'{plugin_dir.name}-<hash>', not under the catalog's name",
                        file_path=plugin_dir,
                        severity=Severity.INFO,
                    )
                )

        return violations

    def _installable(self, plugin_dir: Path) -> bool:
        """Whether ``grok plugin install`` accepts *plugin_dir* with no manifest."""
        skills = plugin_dir / grok.COMPONENT_PATHS["skills"][0]
        if any(safe_is_file(child / "SKILL.md") for child in _children(skills)):
            return True
        agents = plugin_dir / grok.COMPONENT_PATHS["agents"][0]
        if any(child.suffix == ".md" and safe_is_file(child) for child in _children(agents)):
            return True
        for field in ("hooks", "mcpServers"):
            if safe_is_file(plugin_dir / grok.COMPONENT_PATHS[field][0]):
                return True
        return False


def _children(directory: Path) -> List[Path]:
    """Entries of *directory*, or none when it cannot be listed."""
    try:
        return list(directory.iterdir())
    except OSError:
        return []
