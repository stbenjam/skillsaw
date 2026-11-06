"""Stateful ZCode plugin and marketplace discovery views.

Discovery gathers ZCode's filesystem evidence without state. This mixin
caches it for ``RepositoryContext`` and applies the ``--type`` gate, the
same seam :class:`~skillsaw.repository_grok.RepositoryGrokMixin` provides
for Grok Build.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Set

from .discovery import zcode as zcode_discovery
from .formats.zcode import PLUGIN_DIR_NAME
from .paths import safe_resolve
from .repository_types import RepositoryType

_ZCODE_TYPES = frozenset({RepositoryType.ZCODE_PLUGIN, RepositoryType.ZCODE_MARKETPLACE})


class RepositoryZCodeMixin:
    """Cached ZCode plugin and catalog discovery for RepositoryContext.

    The host supplies the repository root, the shared walk's view of the
    reserved ``.zcode-plugin`` directories, and the exclusion predicate.
    """

    if TYPE_CHECKING:
        root_path: Path
        skills: List[Path]
        zcode_plugins: List[Path]
        _zcode_catalog_paths: Optional[List[Path]]
        _zcode_claims: Optional[Set[Path]]
        _zcode_roots: Optional[List[Path]]
        _zcode_discovery_enabled: bool
        _zcode_plugin_forced: bool
        _zcode_marketplace_forced: bool

        def agent_tool_dirs(self, name: str) -> List[Path]: ...

        def is_path_excluded(self, path: Path) -> bool: ...

        def _live_plugin_roots(self) -> Set[Path]: ...

        @staticmethod
        def _under_any(path: Path, roots: Set[Path]) -> bool: ...

    def _init_zcode(self, repo_types: Optional[Iterable[RepositoryType]]) -> None:
        """Set up ZCode caches and the ``--type`` gate, then discover plugins.

        An override decides what discovery walks and which format rules
        activate, never what the author declared: ``provenance()`` reads the
        marker off the filesystem, and :meth:`_zcode_catalog_files` reads
        the catalog past this gate.
        """
        selected = None
        if repo_types is not None:
            selected_types = set(repo_types)
            selected = bool(selected_types & _ZCODE_TYPES)
            self._zcode_plugin_forced = RepositoryType.ZCODE_PLUGIN in selected_types
            self._zcode_marketplace_forced = RepositoryType.ZCODE_MARKETPLACE in selected_types
        else:
            self._zcode_plugin_forced = False
            self._zcode_marketplace_forced = False
        self._zcode_discovery_enabled = selected is not False
        self._zcode_catalog_paths = None
        self._zcode_claims = None
        self._zcode_roots = None
        self.zcode_plugins = self._discover_zcode_plugins() if self._zcode_discovery_enabled else []

    def _zcode_marker_dirs(self) -> List[Path]:
        """Every non-excluded ``.zcode-plugin`` directory, from the shared walk."""
        return self.agent_tool_dirs(PLUGIN_DIR_NAME)

    def _enumerate_zcode_catalogs(self, *, forced: bool) -> List[Path]:
        root = safe_resolve(self.root_path)
        if root is None:
            return []
        return zcode_discovery.enumerate_zcode_catalogs(
            self.root_path,
            root,
            bool(self._zcode_marker_dirs()),
            self.is_path_excluded,
            seed_forced_primary=forced,
        )

    def zcode_marketplace_paths(self) -> List[Path]:
        """The discovered ZCode catalog, honoring the ``--type`` gate."""
        if self._zcode_catalog_paths is None:
            self._zcode_catalog_paths = (
                self._enumerate_zcode_catalogs(forced=self._zcode_marketplace_forced)
                if self._zcode_discovery_enabled
                else []
            )
        return list(self._zcode_catalog_paths)

    def _zcode_catalog_files(self) -> List[Path]:
        """The ZCode catalog present in the checkout, independent of ``--type``.

        Provenance reads author declarations, which an override does not
        change, so this bypasses the discovery gate.
        """
        return self._enumerate_zcode_catalogs(forced=False)

    def zcode_root_catalog_exists(self) -> bool:
        """Whether the repository root carries a ZCode catalog."""
        return bool(self._zcode_catalog_files())

    def zcode_local_source_dirs(self) -> List[Path]:
        """Resolved plugin directories the ZCode catalog lists as local sources."""
        return zcode_discovery.zcode_local_sources(self._zcode_catalog_files())

    def zcode_listed_source_dirs(self) -> List[Path]:
        """Local sources of every catalog being linted, a forced one included."""
        return zcode_discovery.zcode_local_sources(
            [*self._zcode_catalog_files(), *self.zcode_marketplace_paths()]
        )

    def _discover_zcode_plugins(self) -> List[Path]:
        """Directories declaring a ZCode plugin (see ``discovery.zcode``)."""
        return [
            path
            for path in zcode_discovery.discover_zcode_plugins(
                self.root_path,
                self._zcode_marker_dirs(),
                # A forced ``--type zcode-marketplace`` lints a catalog no
                # marker declares; its local plugins come with it.
                self.zcode_listed_source_dirs(),
                forced=self._zcode_plugin_forced,
            )
            if not self.is_path_excluded(path)
        ]

    def _zcode_claim_set(self) -> Set[Path]:
        """Every resolved directory ZCode claims, computed once per context.

        Discovered plugin roots plus the catalog's local sources. The marker
        half of the evidence is asked directly by ``provenance()``, which is
        what keeps a declared plugin declared under a ``--type`` override
        that switched this discovery off.
        """
        if self._zcode_claims is None:
            claims = {r for r in (safe_resolve(p) for p in self.zcode_plugins) if r is not None}
            claims.update(self.zcode_local_source_dirs())
            # Marker-backed roots are declarations, so they stay claimed when
            # a ``--type`` override switches discovery off.
            claims.update(
                r
                for p in zcode_discovery.discover_zcode_plugins(
                    self.root_path, self._zcode_marker_dirs(), ()
                )
                if (r := safe_resolve(p)) is not None
            )
            self._zcode_claims = claims
        return self._zcode_claims

    def zcode_plugin_roots(self) -> List[Path]:
        """Resolved ZCode plugin roots, excluded directories dropped."""
        if self._zcode_roots is None:
            self._zcode_roots = sorted(
                root for root in self._zcode_claim_set() if not self.is_path_excluded(root)
            )
        return self._zcode_roots

    def _reset_zcode_caches(self, filtering: bool = False) -> None:
        """Drop every cached ZCode view; re-run discovery when excludes narrowed.

        Called from ``apply_excludes``. An exclusion can drop the catalog,
        which may be the only source for a plugin whose own path matches no
        pattern, so *filtering* re-probes and prunes that plugin's skills.
        """
        before = set(self._zcode_claim_set())
        self._zcode_catalog_paths = None
        self._zcode_claims = None
        self._zcode_roots = None
        if not filtering:
            self._zcode_claim_set()
            return
        if self._zcode_discovery_enabled:
            self.zcode_plugins = self._discover_zcode_plugins()
        dropped = before - self._zcode_claim_set()
        if dropped:
            kept = self._live_plugin_roots()
            self.skills = [
                skill
                for skill in self.skills
                if not self._under_any(skill, dropped) or self._under_any(skill, kept)
            ]
