"""Stateful Grok Build plugin and marketplace discovery views.

Discovery gathers Grok's filesystem evidence without state. This mixin is
the small stateful seam that caches it for ``RepositoryContext`` and applies
the ``--type`` gate, keeping the orchestrator itself free of another
ecosystem's bookkeeping.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Set

from .discovery import grok as grok_discovery
from .formats.grok import PLUGIN_DIR_NAME
from .paths import safe_resolve
from .repository_types import RepositoryType

#: The two types the ``--type`` gate selects on. Members rather than their
#: string values, so a renamed enum member is a type error here instead of a
#: silently disabled gate.
_GROK_TYPES = frozenset({RepositoryType.GROK_PLUGIN, RepositoryType.GROK_MARKETPLACE})


class RepositoryGrokMixin:
    """Cached Grok plugin and catalog discovery behavior for RepositoryContext.

    The host supplies the repository root, the shared walk's view of the
    reserved ``.grok-plugin`` directories, and the exclusion predicate.
    """

    if TYPE_CHECKING:
        root_path: Path
        plugins: List[Path]
        codex_plugins: List[Path]
        agent_plugins: List[Path]
        skills: List[Path]
        grok_plugins: List[Path]
        _grok_catalog_paths: Optional[List[Path]]
        _grok_claims: Optional[Set[Path]]
        _grok_roots: Optional[List[Path]]
        _grok_discovery_enabled: bool
        _grok_plugin_forced: bool
        _grok_marketplace_forced: bool

        def agent_tool_dirs(self, name: str) -> List[Path]: ...

        def is_path_excluded(self, path: Path) -> bool: ...

        @staticmethod
        def _under_any(path: Path, roots: Set[Path]) -> bool: ...

    def _init_grok(self, repo_types: Optional[Iterable[RepositoryType]]) -> None:
        """Set up Grok caches and the ``--type`` gate, then discover plugins.

        The gate mirrors Codex's: an override decides which catalogs are
        *walked* and which format rules activate, never what the author
        declared — ``provenance()`` reads the marker straight off the
        filesystem and :meth:`_grok_catalog_files` re-enumerates catalogs
        past this gate, so a declared or catalog-claimed directory keeps its
        container and prose in the lint tree either way. ``GROK_PROJECT`` is
        deliberately not a gate value: ``.grok/`` is project configuration,
        not a plugin claim.
        """
        selected = None
        if repo_types is not None:
            selected_types = set(repo_types)
            selected = bool(selected_types & _GROK_TYPES)
            self._grok_plugin_forced = RepositoryType.GROK_PLUGIN in selected_types
            self._grok_marketplace_forced = RepositoryType.GROK_MARKETPLACE in selected_types
        else:
            self._grok_plugin_forced = False
            self._grok_marketplace_forced = False
        self._grok_discovery_enabled = selected is not False
        self._grok_catalog_paths = None
        self._grok_claims = None
        self._grok_roots = None
        self.grok_plugins = self._discover_grok_plugins() if self._grok_discovery_enabled else []

    def _grok_marker_dirs(self) -> List[Path]:
        """Every non-excluded ``.grok-plugin`` directory, from the shared walk."""
        return self.agent_tool_dirs(PLUGIN_DIR_NAME)

    def _discover_grok_marketplaces(self) -> List[Path]:
        """Discovery-side view of the catalog enumerator: honors the ``--type``
        gate, caches per context, and seeds the root entrypoint when the type
        was forced.
        """
        if self._grok_catalog_paths is None:
            if not self._grok_discovery_enabled:
                self._grok_catalog_paths = []
            else:
                root = safe_resolve(self.root_path) or self.root_path
                self._grok_catalog_paths = grok_discovery.enumerate_grok_catalogs(
                    self.root_path,
                    root,
                    self._grok_marker_dirs(),
                    self.is_path_excluded,
                    seed_forced_primary=self._grok_marketplace_forced,
                )
        return self._grok_catalog_paths

    def grok_marketplace_paths(self) -> List[Path]:
        """Every discovered Grok catalog file."""
        return list(self._discover_grok_marketplaces())

    def has_grok_marketplace(self) -> bool:
        """Whether a Grok catalog is present.

        Existence, not parseability — a catalog with broken JSON must still
        activate the Grok rules so they can report it.
        """
        return bool(self._discover_grok_marketplaces())

    def _grok_catalog_files(self) -> List[Path]:
        """Grok catalog files present in the checkout, asked of the filesystem.

        Independent of the ``--type`` gate by design: the provenance claim
        set and :meth:`grok_catalog_exists` read author *declarations*,
        which an override does not change — reading them from discovery
        would make ``--type marketplace`` restore the false positives the
        stand-downs exist to remove.
        """
        resolved_root = safe_resolve(self.root_path)
        if resolved_root is None:
            return []
        return grok_discovery.enumerate_grok_catalogs(
            self.root_path,
            resolved_root,
            self._grok_marker_dirs(),
            self.is_path_excluded,
        )

    def grok_catalog_exists(self) -> bool:
        """Whether any Grok catalog file is present in the checkout."""
        return bool(self._grok_catalog_files())

    def _grok_local_sources(self) -> List[Path]:
        """Local plugin directories declared by a Grok catalog."""
        # Filesystem-enumerated, not discovery-gated: these feed the
        # provenance claim set, which must be ``--type``-invariant.
        return grok_discovery.grok_local_sources(self._grok_catalog_files())

    def grok_local_source_dirs(self) -> List[Path]:
        """Resolved plugin directories a Grok catalog claims as a local source.

        The declaration side of the claim set rather than the set itself:
        "a catalog addresses this directory by name" is a different fact
        from "Grok owns this directory", and only the first decides whether
        a manifest-less directory installs under a synthesized name that
        nothing can then ask for.
        """
        return list(self._grok_local_sources())

    def _discover_grok_plugins(self) -> List[Path]:
        """Directories declaring a Grok plugin (see ``discovery.grok``)."""
        return [
            path
            for path in grok_discovery.discover_grok_plugins(
                self.root_path,
                self._grok_marker_dirs(),
                self._grok_local_sources(),
                forced=self._grok_plugin_forced,
            )
            if not self.is_path_excluded(path)
        ]

    def _grok_claim_set(self) -> Set[Path]:
        """Every resolved directory Grok claims, computed once per context.

        The union of discovered plugin roots and the catalogs' local
        sources. The marker half of the evidence does not come from here —
        ``provenance()`` asks ``grok_manifest_is_contained`` directly, which
        is what keeps a declared plugin declared under a ``--type`` override
        that switched this discovery off. What the union adds is the catalog
        claims and the seed a forced ``--type grok-plugin`` needs, so the
        check the operator asked for has a node to run against. Rebuilding
        it per call would make repository detection quadratic in the catalog
        size.
        """
        if self._grok_claims is None:
            claims = {r for r in (safe_resolve(p) for p in self.grok_plugins) if r is not None}
            claims.update(self._grok_local_sources())
            self._grok_claims = claims
        return self._grok_claims

    def grok_plugin_roots(self) -> List[Path]:
        """Resolved Grok plugin roots, computed once per context.

        ``grok_plugin_owning`` runs per consulted path, so resolving every
        root on each call would cost a filesystem round-trip per question.
        Excluded directories are dropped, as Codex drops them: an ownership
        answer over a directory the lint tree never built is an owner
        nothing can consult.
        """
        if self._grok_roots is None:
            self._grok_roots = sorted(
                root for root in self._grok_claim_set() if not self.is_path_excluded(root)
            )
        return self._grok_roots

    def _reset_grok_caches(self, filtering: bool = False) -> None:
        """Drop every cached Grok view; re-run discovery when excludes narrowed.

        Called from ``apply_excludes``. The clear is unconditional because
        the claim set folds in both plugin roots and catalog sources and an
        exclude can drop either, while *filtering* — true only when the
        context actually carries exclude patterns — re-probes: a newly
        excluded catalog may be the only source for a plugin whose own path
        matches no pattern.
        """
        before = {r for r in (safe_resolve(p) for p in self.grok_plugins) if r is not None}
        self._grok_catalog_paths = None
        self._grok_claims = None
        self._grok_roots = None
        if filtering and self._grok_discovery_enabled:
            self.grok_plugins = self._discover_grok_plugins()
            self._prune_skills_of_dropped_grok_plugins(before)

    def _prune_skills_of_dropped_grok_plugins(self, before: Set[Path]) -> None:
        """Drop skills whose only owner left the Grok set, as the Codex arm does.

        A plugin claimed by a catalog alone leaves ``grok_plugins`` when that
        catalog is excluded, while its skills were discovered by the shared
        walk and stay in ``self.skills`` — where they attach as standalone
        nodes and keep linting the very content the exclusion removed. A
        skill any other active plugin still claims keeps its owner and is
        preserved — including a nested Grok plugin of its own, which the
        re-probe kept because it carries a manifest.
        """
        dropped = before - {
            r for r in (safe_resolve(p) for p in self.grok_plugins) if r is not None
        }
        if not dropped:
            return
        active = {
            r
            for p in (
                *self.plugins,
                *self.codex_plugins,
                *self.agent_plugins,
                *self.grok_plugins,
            )
            if (r := safe_resolve(p)) is not None
        }
        self.skills = [
            skill
            for skill in self.skills
            if not self._under_any(skill, dropped) or self._under_any(skill, active)
        ]
