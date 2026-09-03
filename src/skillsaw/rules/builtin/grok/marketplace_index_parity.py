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
from typing import Any, Dict, FrozenSet, List, Optional, Set

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import parse_frontmatter, read_json, read_text

from ._helpers import GROK_MARKETPLACE_REPO_TYPES, sample

#: The file Grok reads a skill from, which is what makes a subdirectory of
#: ``skills/`` a skill rather than a folder of notes.
_SKILL_FILE = "SKILL.md"


@dataclass(frozen=True)
class _Skill:
    """One skill on disk, under every name the index may call it by.

    The upstream generator writes the SKILL.md frontmatter ``name`` and
    falls back to the directory name, so an index that is exactly right can
    carry either. Matching on both is what keeps a skill whose declared name
    differs from its directory out of the drift lists twice over.
    """

    display: str
    names: FrozenSet[str]


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
    malformed_in_index: List[str] = field(default_factory=list)
    sha_catalog_only: List[str] = field(default_factory=list)
    sha_index_only: List[str] = field(default_factory=list)
    sha_differs: List[str] = field(default_factory=list)
    skills_index_only: List[str] = field(default_factory=list)
    skills_disk_only: List[str] = field(default_factory=list)

    def parts(self) -> List[str]:
        labelled = (
            ("not in the index", self.missing_from_index),
            ("not in the catalog", self.unknown_in_index),
            ("entries that are not objects", self.malformed_in_index),
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
            index_nodes = catalog_node.find(GrokMarketplaceIndexNode)
            # The tree marks a file at a fallback catalog location, which
            # Grok never reads and so has nothing to compare against.
            violations.extend(
                self._stray_violation(node.path, catalog_node.path)
                for node in index_nodes
                if node.stray
            )
            read = [node for node in index_nodes if not node.stray]
            if not read:
                # An absent index is the documented case, not a defect.
                continue
            entries = self._catalog_entries(catalog_node.path)
            for index_node in read:
                violations.extend(self._check_index(index_node.path, catalog_node.path, entries))

        return violations

    def _stray_violation(self, index: Path, catalog: Path) -> RuleViolation:
        """A display catalog Grok never reads because it is in the wrong place."""
        return self.violation(
            f"'{grok.PLUGIN_INDEX_FILENAME}' is not beside "
            f"'{catalog.parent.name}/{catalog.name}', where Grok reads it",
            file_path=index,
        )

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
        # Built once: the intersection below runs per catalog entry, and both
        # sides are repository-sized.
        index_keys = set(plugins)

        for entry in entries:
            matched = sorted(entry.names & index_keys)
            if not matched:
                drift.missing_from_index.append(entry.display)
                continue
            key = matched[0]
            claimed.add(key)
            listed = plugins.get(key)
            if not isinstance(listed, dict):
                # A key whose value is not an object: Grok has nothing to
                # display for it, and it is claimed, so no other branch
                # would ever name it.
                drift.malformed_in_index.append(key)
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
        """A local source has no ``sha`` to gate on, so a stale index is shown.

        A ``components`` object that is absent, has no ``skills`` key, or
        holds a non-list under it displays no skills at all, so each is an
        empty listing rather than a comparison to skip: the browser shows
        nothing for a plugin that ships skills.
        """
        components = listed.get("components")
        declared = components.get("skills") if isinstance(components, dict) else None
        index_names = (
            {
                item["name"]
                for item in declared
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            if isinstance(declared, list)
            else set()
        )
        disk = self._disk_skills(entry.plugin_dir)
        matched = {name for skill in disk for name in skill.names & index_names}
        for name in sorted(index_names - matched):
            drift.skills_index_only.append(f"{entry.display}/{name}")
        for skill in disk:
            if not skill.names & index_names:
                drift.skills_disk_only.append(f"{entry.display}/{skill.display}")

    def _disk_skills(self, plugin_dir: Optional[Path]) -> List[_Skill]:
        """Skills the plugin on disk ships, as the index generator sees them.

        Mirrors ``plugin_catalog.py``, which is what writes the file this
        rule compares against: the conventional ``skills/`` is scanned one
        level deep, a declared ``skills`` path is a skill directory *itself*
        rather than a folder of them, and the two are unioned rather than
        one replacing the other. The runtime disagrees on both counts — it
        replaces the conventional directory and scans one level under the
        declared one — so a skill either reader loads is carried here, and
        drift is reported only for a name neither produces.
        """
        if plugin_dir is None:
            return []
        found: Dict[Path, _Skill] = {}

        def _record(directory: Path) -> None:
            resolved = safe_resolve(directory)
            if resolved is None or resolved in found or not safe_is_file(directory / _SKILL_FILE):
                return
            found[resolved] = _Skill(
                display=directory.name, names=self._skill_names(directory / _SKILL_FILE, directory)
            )

        def _record_children(directory: Path) -> None:
            try:
                children = sorted(directory.iterdir())
            except OSError:
                return
            for child in children:
                _record(child)

        _record_children(plugin_dir / grok.COMPONENT_PATHS["skills"][0])
        for declared in grok.grok_declared_skill_dirs(plugin_dir):
            _record(declared)
            _record_children(declared)
        return list(found.values())

    def _skill_names(self, skill_md: Path, directory: Path) -> FrozenSet[str]:
        """Every name the generator could have written for this skill.

        The frontmatter ``name`` with the directory name as fallback, as
        ``plugin_catalog.py`` does it — and both when they differ, so an
        index carrying either one is right rather than drifted.
        """
        content = read_text(skill_md)
        data = parse_frontmatter(content)[0] if content is not None else None
        declared = data.get("name") if isinstance(data, dict) else None
        names = {directory.name}
        if isinstance(declared, str) and declared:
            names.add(declared)
        return frozenset(names)

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
