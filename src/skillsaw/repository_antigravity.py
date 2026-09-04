"""Stateful Antigravity plugin discovery views.

Discovery gathers Antigravity's filesystem evidence without state. This
mixin is the small stateful seam that caches it for ``RepositoryContext``
and applies the ``--type`` gate, keeping the orchestrator itself free of
another ecosystem's bookkeeping.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Set

from .discovery import antigravity as antigravity_discovery
from .formats.antigravity import ANTIGRAVITY_CONFIG_DIR_NAMES, PLUGINS_REGISTRY
from .paths import safe_resolve
from .repository_types import RepositoryType

#: The type the ``--type`` gate selects on. A member rather than its string
#: value, so a renamed enum member is a type error here instead of a
#: silently disabled gate. ``ANTIGRAVITY`` is deliberately absent: a
#: customization root is project configuration, not a plugin claim.
_ANTIGRAVITY_TYPES = frozenset({RepositoryType.ANTIGRAVITY_PLUGIN})


class RepositoryAntigravityMixin:
    """Cached Antigravity plugin discovery behavior for RepositoryContext.

    The host supplies the repository root, the shared walk's view of the
    four customization roots, and the exclusion predicate.
    """

    if TYPE_CHECKING:
        root_path: Path
        plugins: List[Path]
        codex_plugins: List[Path]
        agent_plugins: List[Path]
        grok_plugins: List[Path]
        skills: List[Path]
        antigravity_plugins: List[Path]
        _antigravity_claims: Optional[Set[Path]]
        _antigravity_roots: Optional[List[Path]]
        _antigravity_workspace_roots: Optional[List[Path]]
        _antigravity_discovery_enabled: bool
        _antigravity_plugin_forced: bool

        def agent_tool_dirs(self, name: str) -> List[Path]: ...

        def is_path_excluded(self, path: Path) -> bool: ...

        @staticmethod
        def _under_any(path: Path, roots: Set[Path]) -> bool: ...

    def _init_antigravity(self, repo_types: Optional[Iterable[RepositoryType]]) -> None:
        """Set up Antigravity caches and the ``--type`` gate, then discover.

        The gate mirrors Codex's and Grok's: an override decides which
        directories are *walked* and which format rules activate, never what
        the author declared — ``provenance()`` reads the manifest straight
        off the filesystem, so a declared plugin keeps its container and
        prose in the lint tree under an unrelated ``--type``.
        """
        selected = None
        if repo_types is not None:
            selected_types = set(repo_types)
            selected = bool(selected_types & _ANTIGRAVITY_TYPES)
            self._antigravity_plugin_forced = RepositoryType.ANTIGRAVITY_PLUGIN in selected_types
        else:
            self._antigravity_plugin_forced = False
        self._antigravity_discovery_enabled = selected is not False
        self._antigravity_claims = None
        self._antigravity_roots = None
        self._antigravity_workspace_roots = None
        self.antigravity_plugins = (
            self._discover_antigravity_plugins() if self._antigravity_discovery_enabled else []
        )

    def antigravity_customization_dirs(self) -> List[Path]:
        """Every non-excluded customization root, from the shared walk.

        ``agy`` walks up from the entry directory to the repository root and
        unions every root it finds, so a monorepo package's own ``.agents/``
        is live configuration and the walk-backed lookup finds both.
        """
        return [
            directory
            for name in ANTIGRAVITY_CONFIG_DIR_NAMES
            for directory in self.agent_tool_dirs(name)
        ]

    def antigravity_workspace_roots(self) -> List[Path]:
        """The customization roots whose prose and config the tree attaches.

        Every dot root, unconditionally: ``.agents/`` and ``.agent/`` are
        names no other tool claims, and a repository that creates one has
        said which tool it means.

        ``_agents/`` and ``_agent/`` are the only non-dot names any tool
        directory list carries, and an ordinary source package is free to
        be called either — so those two are attached only where the root
        declares one of Antigravity's own files. Without the gate a package
        named ``_agents/`` anywhere in a checkout contributes its
        ``rules/**/*.md`` as always-on instruction prose to a repository
        that configures no Antigravity at all, and ``agy`` walks *up* from
        the entry directory, so a nested one is live configuration for far
        fewer checkouts than the walk finds it in.

        A *file*, not the wider detection marker: ``rules/`` and
        ``agents/`` are the prose this method decides whether to attach, so
        admitting them would let the directory vouch for itself.
        """
        if self._antigravity_workspace_roots is None:
            roots: List[Path] = []
            for name in ANTIGRAVITY_CONFIG_DIR_NAMES:
                gated = not name.startswith(".")
                for directory in self.agent_tool_dirs(name):
                    if gated and not antigravity_discovery.customization_root_declares_a_file(
                        directory, is_excluded=self.is_path_excluded
                    ):
                        continue
                    roots.append(directory)
            self._antigravity_workspace_roots = roots
        return self._antigravity_workspace_roots

    def _discover_antigravity_plugins(self) -> List[Path]:
        """Directories declaring an Antigravity plugin."""
        return [
            path
            for path in antigravity_discovery.discover_antigravity_plugins(
                self.root_path,
                self.antigravity_customization_dirs(),
                forced=self._antigravity_plugin_forced,
            )
            if not self.is_path_excluded(path)
        ]

    def antigravity_registry_dirs(self, filename: str) -> List[Path]:
        """Directories every customization root's *filename* registry names.

        Filesystem-enumerated rather than discovery-gated, for the reason
        Grok's catalog sources are: these feed the provenance claim set,
        which must be ``--type``-invariant.
        """
        return antigravity_discovery.resolve_registry_entries(
            self.root_path,
            self.antigravity_customization_dirs(),
            filename,
            is_excluded=self.is_path_excluded,
        )

    def _antigravity_registry_plugin_roots(self) -> List[Path]:
        """Plugin roots a ``plugins.json`` names outside the install location."""
        return [
            path
            for path in antigravity_discovery.registry_plugin_roots(
                self.antigravity_registry_dirs(PLUGINS_REGISTRY)
            )
            if not self.is_path_excluded(path)
        ]

    def _antigravity_claim_set(self) -> Set[Path]:
        """Every resolved directory Antigravity claims, computed once.

        The union of the discovered plugin roots and the plugin roots a
        ``plugins.json`` registry names: a registry points ``agy`` at
        plugins living outside ``<root>/plugins/``, and a plugin it loads
        brings its hooks, MCP servers, skills and agents with it. The
        marker half of the evidence does not come from here —
        ``provenance()`` asks ``antigravity_manifest_is_contained``
        directly, which is what keeps a declared plugin declared under a
        ``--type`` override that switched this discovery off. What the
        union adds is the registry claims and the seed a forced ``--type
        antigravity-plugin`` needs, so the check the operator asked for has
        a node to run against.

        Registry claims join here rather than ``antigravity_plugins``,
        mirroring Grok: the claim half is ``--type``-invariant while the
        list the format rules discover from stays gated.
        """
        if self._antigravity_claims is None:
            claims = {
                r for r in (safe_resolve(p) for p in self.antigravity_plugins) if r is not None
            }
            claims.update(self._antigravity_registry_plugin_roots())
            self._antigravity_claims = claims
        return self._antigravity_claims

    def antigravity_plugin_roots(self) -> List[Path]:
        """Resolved Antigravity plugin roots, computed once per context.

        Excluded directories are dropped, as Codex and Grok drop them: an
        ownership answer over a directory the lint tree never built is an
        owner nothing can consult.
        """
        if self._antigravity_roots is None:
            self._antigravity_roots = sorted(
                root for root in self._antigravity_claim_set() if not self.is_path_excluded(root)
            )
        return self._antigravity_roots

    def _reset_antigravity_caches(self, filtering: bool = False) -> None:
        """Drop every cached Antigravity view; re-run discovery when excludes narrowed."""
        before = {r for r in (safe_resolve(p) for p in self.antigravity_plugins) if r is not None}
        self._antigravity_claims = None
        self._antigravity_roots = None
        self._antigravity_workspace_roots = None
        if filtering and self._antigravity_discovery_enabled:
            self.antigravity_plugins = self._discover_antigravity_plugins()
            self._prune_skills_of_dropped_antigravity_plugins(before)

    def _prune_skills_of_dropped_antigravity_plugins(self, before: Set[Path]) -> None:
        """Drop skills whose only owner left the set, as the Codex arm does.

        A plugin excluded by pattern leaves ``antigravity_plugins`` while
        its skills were discovered by the shared walk and stay in
        ``self.skills`` — where they attach as standalone nodes and keep
        linting the very content the exclusion removed.
        """
        dropped = before - {
            r for r in (safe_resolve(p) for p in self.antigravity_plugins) if r is not None
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
                *self.antigravity_plugins,
            )
            if (r := safe_resolve(p)) is not None
        }
        self.skills = [
            skill
            for skill in self.skills
            if not self._under_any(skill, dropped) or self._under_any(skill, active)
        ]
