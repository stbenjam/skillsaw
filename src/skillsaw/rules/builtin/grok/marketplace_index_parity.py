"""
Rule: grok-marketplace-index-parity

``plugin-index.json`` is the sole source of the component listing the
marketplace browser shows before anything is installed, and a ``require_sha``
deployment installs from the ``sha`` values it publishes. It is optional and
never repaired: for a url source Grok gates the listing on ``sha`` equality
with the catalog, so drift silently blanks it; for a local source there is
no ``sha`` to gate on, so a stale index is displayed while the plugin on
disk says otherwise. A name in the index with no catalog entry, and a
malformed index, are both ignored without a word.

One consolidated finding per index file: a drifted index is one regeneration
for the author, and a finding per plugin would bury the rest of the run.

Only :class:`GrokMarketplaceIndexNode`, attached under its catalog, is
iterated — a node type only Grok populates, so the rule declares no
``provenance_scope``.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import read_json

from ._helpers import GROK_MARKETPLACE_REPO_TYPES, sample

#: Where a ``plugin-index.json`` is never read: beside either catalog
#: location Grok falls back to, once ``.grok-plugin/marketplace.json`` has
#: won. Derived from the catalog order rather than restated, so a change to
#: the fallbacks moves this with it.
_UNREAD_INDEX_DIRS = tuple(parts[:-1] for parts in grok.CATALOG_PATHS[1:])

#: The file Grok reads a skill from, which is what makes a subdirectory of
#: ``skills/`` a skill rather than a folder of notes.
_SKILL_FILE = "SKILL.md"


@dataclass
class _Entry:
    """One catalog entry, reduced to what parity needs."""

    display: str
    names: Set[str]
    sha: Optional[str]
    plugin_dir: Optional[Path]


@dataclass
class _Drift:
    """Every disagreement found between one catalog and one index."""

    missing_from_index: List[str] = field(default_factory=list)
    unknown_in_index: List[str] = field(default_factory=list)
    sha_catalog_only: List[str] = field(default_factory=list)
    sha_index_only: List[str] = field(default_factory=list)
    sha_differs: List[str] = field(default_factory=list)
    skills_index_only: List[str] = field(default_factory=list)
    skills_disk_only: List[str] = field(default_factory=list)

    def parts(self) -> List[str]:
        labelled = (
            ("not in the index", self.missing_from_index),
            ("not in the catalog", self.unknown_in_index),
            ("'sha' in the catalog only", self.sha_catalog_only),
            ("'sha' in the index only", self.sha_index_only),
            ("'sha' differs", self.sha_differs),
            ("skills only the index lists", self.skills_index_only),
            ("skills only the plugin ships", self.skills_disk_only),
        )
        # Deduplicated: a catalog listing one name twice is one defect for
        # grok-marketplace-json-valid to report, not two drifted names here.
        return [f"{label}: {sample(sorted(set(names)))}" for label, names in labelled if names]


class GrokMarketplaceIndexParityRule(Rule):
    """Check a Grok Build plugin index against the catalog beside it"""

    since = "0.20.0"

    repo_types = GROK_MARKETPLACE_REPO_TYPES

    config_schema = {
        "check-components": {
            "type": "bool",
            "default": True,
            "description": (
                "Compare the skills the index lists for a local source against the "
                "skills that plugin ships"
            ),
        },
    }

    @property
    def rule_id(self) -> str:
        return "grok-marketplace-index-parity"

    @property
    def description(self) -> str:
        return ".grok-plugin/plugin-index.json must agree with the catalog beside it"

    def default_severity(self) -> Severity:
        # The catalog still loads and every plugin still installs; what
        # drifts is what the browser shows before anyone installs it.
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for catalog_node in context.lint_tree.find(GrokMarketplaceConfigNode):
            violations.extend(self._check_stray(catalog_node.path))
            index_nodes = catalog_node.find(GrokMarketplaceIndexNode)
            if not index_nodes:
                # An absent index is the documented case, not a defect.
                continue
            entries = self._catalog_entries(catalog_node.path)
            for index_node in index_nodes:
                violations.extend(self._check_index(index_node.path, catalog_node.path, entries))

        return violations

    def _check_stray(self, catalog: Path) -> List[RuleViolation]:
        """A display catalog Grok never reads because it is in the wrong place."""
        marketplace_root = catalog.parent.parent
        violations: List[RuleViolation] = []
        for parts in _UNREAD_INDEX_DIRS:
            candidate = marketplace_root.joinpath(*parts, grok.PLUGIN_INDEX_FILENAME)
            if safe_is_file(candidate):
                violations.append(
                    self.violation(
                        f"'{grok.PLUGIN_INDEX_FILENAME}' is not beside "
                        f"'{catalog.parent.name}/{catalog.name}', where Grok reads it",
                        file_path=candidate,
                    )
                )
        return violations

    def _check_index(
        self, index: Path, catalog: Path, entries: Optional[List[_Entry]]
    ) -> List[RuleViolation]:
        data, error = read_json(index)
        if error:
            return [self.violation(f"Invalid JSON: {error}", file_path=index)]
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, dict):
            return [
                self.violation("'plugins' must be an object keyed by plugin name", file_path=index)
            ]
        if entries is None:
            # The catalog itself is unreadable; grok-marketplace-json-valid
            # names that defect, and comparing against nothing would report
            # every plugin as missing.
            return []

        drift = self._compare(entries, plugins)
        parts = drift.parts()
        if not parts:
            return []
        return [
            self.violation(
                f"{index.name} disagrees with {catalog.name}: " + "; ".join(parts),
                file_path=index,
            )
        ]

    def _compare(self, entries: List[_Entry], plugins: Dict[str, Any]) -> _Drift:
        drift = _Drift()
        claimed: Set[str] = set()
        check_components = self.setting("check-components")

        for entry in entries:
            matched = sorted(entry.names & set(plugins))
            if not matched:
                drift.missing_from_index.append(entry.display)
                continue
            key = matched[0]
            claimed.add(key)
            listed = plugins.get(key)
            if not isinstance(listed, dict):
                continue
            self._compare_sha(entry, listed, drift)
            if check_components and entry.plugin_dir is not None:
                self._compare_skills(entry, listed, drift)

        for key in plugins:
            if key not in claimed:
                drift.unknown_in_index.append(key)

        return drift

    def _compare_sha(self, entry: _Entry, listed: Dict[str, Any], drift: _Drift) -> None:
        listed_sha = listed.get("sha")
        listed_sha = listed_sha if isinstance(listed_sha, str) and listed_sha else None
        if entry.sha and listed_sha is None:
            drift.sha_catalog_only.append(entry.display)
        elif listed_sha and entry.sha is None:
            drift.sha_index_only.append(entry.display)
        elif entry.sha and listed_sha and entry.sha.lower() != listed_sha.lower():
            # Compared case-insensitively: the installer treats a commit id
            # that way, and grok-marketplace-json-valid already owns the
            # casing on its own.
            drift.sha_differs.append(entry.display)

    def _compare_skills(self, entry: _Entry, listed: Dict[str, Any], drift: _Drift) -> None:
        """A local source has no ``sha`` to gate on, so a stale index is shown."""
        components = listed.get("components")
        if not isinstance(components, dict):
            return
        declared = components.get("skills")
        if not isinstance(declared, list):
            return
        index_names = {
            item.get("name")
            for item in declared
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        disk_names = self._skill_names(entry.plugin_dir)
        for name in index_names - disk_names:
            drift.skills_index_only.append(f"{entry.display}/{name}")
        for name in disk_names - index_names:
            drift.skills_disk_only.append(f"{entry.display}/{name}")

    def _skill_names(self, plugin_dir: Optional[Path]) -> Set[str]:
        """Skills the plugin on disk ships, following a manifest override.

        A declared ``skills`` path replaces the conventional directory
        rather than adding to it, so a manifest that names one is read
        instead of ``skills/``, not alongside it.
        """
        if plugin_dir is None:
            return set()
        if "skills" in grok.grok_manifest(plugin_dir):
            directories = grok.grok_declared_skill_dirs(plugin_dir)
        else:
            conventional = plugin_dir / grok.COMPONENT_PATHS["skills"][0]
            directories = [conventional] if safe_is_dir(conventional) else []
        names: Set[str] = set()
        for directory in directories:
            try:
                children = list(directory.iterdir())
            except OSError:
                continue
            names.update(child.name for child in children if safe_is_file(child / _SKILL_FILE))
        return names

    def _catalog_entries(self, catalog: Path) -> Optional[List[_Entry]]:
        """The catalog reduced to parity inputs, or ``None`` when unusable."""
        data, error = read_json(catalog)
        if error or not isinstance(data, dict):
            return None
        entries = data.get("plugins")
        if not isinstance(entries, list):
            return None

        marketplace_root = catalog.parent.parent
        resolved_root = safe_resolve(marketplace_root)
        found: List[_Entry] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            name = name if isinstance(name, str) and name else None
            plugin_dir = self._local_dir(entry.get("source"), marketplace_root, resolved_root)
            resolved = grok.grok_plugin_name(plugin_dir) if plugin_dir is not None else None
            names = {value for value in (name, resolved) if value}
            if not names:
                continue
            source = entry.get("source")
            sha = source.get("sha") if isinstance(source, dict) else None
            found.append(
                _Entry(
                    display=name or resolved or "",
                    names=names,
                    sha=sha if isinstance(sha, str) and sha else None,
                    plugin_dir=plugin_dir,
                )
            )
        return found

    def _local_dir(
        self, source: Any, marketplace_root: Path, resolved_root: Optional[Path]
    ) -> Optional[Path]:
        local = grok.grok_local_source_path(source)
        if local is None or resolved_root is None:
            return None
        target = contained_resolve(marketplace_root / local, resolved_root)
        return target if target is not None and safe_is_dir(target) else None
