"""
Rule: grok-marketplace-index-parity

Verifies that ``.grok-plugin/plugin-index.json`` matches the declarations in
``.grok-plugin/marketplace.json``. Grok Build uses the index to display
plugin metadata and available components in the marketplace browser. Keeping
both files in sync ensures users see accurate component details.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.utils import parse_frontmatter, read_text, strict_json

from ._helpers import GROK_MARKETPLACE_REPO_TYPES, SAMPLE_LIMIT, sample


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

    # Sets, not lists: ``parts()`` deduplicates and sorts, so nothing
    # downstream reads order or multiplicity. The six entry-keyed fields are
    # bounded by the catalog that way; the two skill fields are not, because
    # their keys are ``entry/skill`` pairs and many entries may name one
    # plugin directory. Those two are capped instead — see :meth:`add_skill`.
    missing_from_index: Set[str] = field(default_factory=set)
    unknown_in_index: Set[str] = field(default_factory=set)
    malformed_in_index: Set[str] = field(default_factory=set)
    sha_catalog_only: Set[str] = field(default_factory=set)
    sha_index_only: Set[str] = field(default_factory=set)
    sha_differs: Set[str] = field(default_factory=set)
    skills_index_only: Set[str] = field(default_factory=set)
    skills_disk_only: Set[str] = field(default_factory=set)

    @staticmethod
    def add_skill(names: Set[str], value: str) -> None:
        """Record one skill drift, collecting no more than are rendered.

        A catalog is repository content, and these keys are
        ``entry/skill`` pairs: ten thousand entries all sourcing one plugin
        directory cross-multiply with that plugin's skills into a set with
        no bound and no wall-clock budget. ``parts()`` renders the capped
        lists as "and more" rather than a count, since past the cap the
        count is a floor.
        """
        if len(names) <= SAMPLE_LIMIT:
            names.add(value)

    def parts(self) -> List[str]:
        labelled = (
            ("not in the index", self.missing_from_index, False),
            ("not in the catalog", self.unknown_in_index, False),
            ("entries that are not objects", self.malformed_in_index, False),
            ("'sha' in the catalog only", self.sha_catalog_only, False),
            ("'sha' in the index only", self.sha_index_only, False),
            ("'sha' differs", self.sha_differs, False),
            ("skills only the index lists", self.skills_index_only, True),
            ("skills only the plugin ships", self.skills_disk_only, True),
        )
        # Deduplicated by the sets above: a catalog listing one name twice
        # is one defect for grok-marketplace-json-valid, not two here.
        return [
            f"{label}: {self._render(names, capped)}" for label, names, capped in labelled if names
        ]

    @staticmethod
    def _render(names: Set[str], capped: bool) -> str:
        ordered = sorted(names)
        if capped and len(ordered) > SAMPLE_LIMIT:
            return f"{sample(ordered[:SAMPLE_LIMIT])}, and more"
        return sample(ordered)


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

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        #: One skill walk per plugin directory, reseeded by every
        #: :meth:`check`. Per instance, never on the class: a shared default
        #: would carry one repository's walk into the next.
        self._skills_by_dir: Dict[Path, List[_Skill]] = {}

    @property
    def rule_id(self) -> str:
        return "grok-marketplace-index-parity"

    @property
    def description(self) -> str:
        return ".grok-plugin/plugin-index.json must agree with the catalog beside it"

    def default_severity(self) -> Severity:
        # Parity describes the browser's metadata. Installation problems
        # are separate findings owned by the catalog validator.
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        # One walk per plugin directory for the whole run: a directory a
        # dozen catalog entries resolve to is read once. Rebound here rather
        # than cleared, so nothing survives into the next run.
        self._skills_by_dir = {}

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
        # Enforce strict JSON parsing to match Grok's parser behavior.
        data, error = strict_json(index)
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
                drift.missing_from_index.add(entry.display)
                continue
            key = matched[0]
            claimed.add(key)
            listed = plugins.get(key)
            if not isinstance(listed, dict):
                # A key whose value is not an object: Grok has nothing to
                # display for it, and it is claimed, so no other branch
                # would ever name it.
                drift.malformed_in_index.add(key)
                continue
            self._compare_sha(entry, listed, drift)
            if check_components and entry.plugin_dir is not None:
                self._compare_skills(entry, listed, drift)

        for key in plugins:
            if key not in claimed:
                drift.unknown_in_index.add(key)

        return drift

    def _compare_sha(self, entry: _Entry, listed: Dict[str, Any], drift: _Drift) -> None:
        listed_sha = listed.get("sha")
        listed_sha = listed_sha if isinstance(listed_sha, str) and listed_sha else None
        if entry.sha and listed_sha is None:
            drift.sha_catalog_only.add(entry.display)
        elif listed_sha and entry.sha is None:
            drift.sha_index_only.add(entry.display)
        elif entry.sha and listed_sha and entry.sha.lower() != listed_sha.lower():
            # Compared case-insensitively: the installer treats a commit id
            # that way, and grok-marketplace-json-valid already owns the
            # casing on its own.
            drift.sha_differs.add(entry.display)

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
            drift.add_skill(drift.skills_index_only, f"{entry.display}/{name}")
        for skill in disk:
            if not skill.names & index_names:
                drift.add_skill(drift.skills_disk_only, f"{entry.display}/{skill.display}")

    def _disk_skills(self, plugin_dir: Optional[Path]) -> List[_Skill]:
        """Skills the plugin on disk ships, as either reader loads them.

        Two readers write and consume this listing and they disagree about
        the conventional directory: ``plugin_catalog.py``, which generates
        the file this rule compares against, unions the declared paths with
        ``skills/``, while the runtime replaces it. Both are walked, so a
        skill either one loads is carried here and drift is reported only
        for a name neither produces.

        The walk itself is the runtime's, measured against 1.0.13: a root —
        conventional or declared — is a skill directory *itself* when it
        holds a ``SKILL.md``, and every directory under it at any depth is
        one too, with no pruning at the first hit.
        """
        if plugin_dir is None:
            return []
        # ``_local_dir`` already resolved this, so it is the containment
        # root the walk below is held to. Resolved before the lookup as
        # well as before the store, so both sides of the memo key on the
        # same path however the caller spelled it.
        plugin_dir = safe_resolve(plugin_dir) or plugin_dir
        memo = self._skills_by_dir.get(plugin_dir)
        if memo is not None:
            return memo
        found: Dict[Path, _Skill] = {}
        seen: Set[Path] = set()

        def _walk(directory: Path) -> None:
            # Contained against the plugin, not merely resolvable: Grok
            # drops a skill directory that leaves the plugin root, and this
            # walk stats and reads the SKILL.md it finds. Iterative and
            # deduplicated on the resolved directory, so a symlink cycle
            # inside the plugin cannot loop.
            stack = [directory]
            while stack:
                current = stack.pop()
                resolved = contained_resolve(current, plugin_dir)
                if resolved is None or resolved in seen or not safe_is_dir(current):
                    continue
                seen.add(resolved)
                skill_md = current / grok.SKILL_FILENAME
                if (
                    resolved not in found
                    and contained_resolve(skill_md, plugin_dir) is not None
                    and safe_is_file(skill_md)
                ):
                    found[resolved] = _Skill(
                        display=current.name,
                        names=self._skill_names(skill_md, current),
                    )
                try:
                    stack.extend(sorted(current.iterdir()))
                except OSError:
                    continue

        _walk(plugin_dir / grok.COMPONENT_PATHS["skills"][0])
        for declared in grok.grok_declared_skill_dirs(plugin_dir):
            _walk(declared)
        skills = list(found.values())
        self._skills_by_dir[plugin_dir] = skills
        return skills

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
        data, error = strict_json(catalog)
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
            source = entry.get("source")
            plugin_dir = self._local_dir(source, marketplace_root, resolved_root)
            if plugin_dir is None and not self._is_usable_url(source):
                # No usable local directory or remote URL to display.
                # The catalog validator names the source problem; there is
                # no discovered entry whose index metadata can be compared.
                continue
            resolved = grok.grok_plugin_name(plugin_dir) if plugin_dir is not None else None
            names = {value for value in (name, resolved) if value}
            if not names:
                continue
            # Only a url source is pinned: Grok reads no ``sha`` on a local
            # one, so carrying it here would report a sha-less index as
            # catalog-only or drifted against a value nothing installs from.
            sha = source.get("sha") if grok.is_url_source(source) else None
            found.append(
                _Entry(
                    display=name or resolved or "",
                    names=names,
                    sha=sha if isinstance(sha, str) and sha else None,
                    plugin_dir=plugin_dir,
                )
            )
        return found

    @staticmethod
    def _is_usable_url(source: Any) -> bool:
        """Whether *source* supplies a remote URL for the display comparison.

        Grok 1.0.13's scanner carries remote subdirectory paths verbatim and
        still attaches matching index components. Their lexical validation
        happens at installation, so rejecting them here would falsely say
        an entry visible in the browser is absent from the catalog.
        """
        if not grok.is_url_source(source):
            return False
        url = source.get("url") if isinstance(source, dict) else None
        return isinstance(url, str) and bool(url)

    def _local_dir(
        self, source: Any, marketplace_root: Path, resolved_root: Optional[Path]
    ) -> Optional[Path]:
        local = grok.grok_local_source_path(source)
        if local is None or resolved_root is None:
            return None
        target = contained_resolve(marketplace_root / local, resolved_root)
        return target if target is not None and safe_is_dir(target) else None
