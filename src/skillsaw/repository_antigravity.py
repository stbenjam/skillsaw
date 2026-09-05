"""Stateful Antigravity plugin discovery views.

Discovery gathers Antigravity's filesystem evidence without state. This
mixin caches it for ``RepositoryContext``. Declared plugins survive every
``--type`` override; forcing the plugin type also discovers missing manifests.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Set

from .discovery import antigravity as antigravity_discovery
from .formats.antigravity import ANTIGRAVITY_CONFIG_DIR_NAMES, PLUGINS_REGISTRY, REGISTRY_FILENAMES
from .paths import safe_resolve
from .repository_types import RepositoryType


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
        skills: List[Path]
        antigravity_plugins: List[Path]
        _antigravity_claims: Optional[Set[Path]]
        _antigravity_roots: Optional[List[Path]]
        _antigravity_workspace_roots: Optional[List[Path]]
        _antigravity_plugin_forced: bool

        def agent_tool_dirs(self, name: str) -> List[Path]: ...

        def grok_plugin_roots(self) -> List[Path]: ...

        def is_path_excluded(self, path: Path) -> bool: ...

        @staticmethod
        def _under_any(path: Path, roots: Set[Path]) -> bool: ...

    def _init_antigravity(self, repo_types: Optional[Iterable[RepositoryType]]) -> None:
        """Initialize caches and discover declared or explicitly requested plugins."""
        self._antigravity_plugin_forced = (
            repo_types is not None and RepositoryType.ANTIGRAVITY_PLUGIN in repo_types
        )
        self._antigravity_claims = None
        self._antigravity_roots = None
        self._antigravity_workspace_roots = None
        self.antigravity_plugins = self._discover_antigravity_plugins()

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

        Every dot root, unconditionally — including ``.agents/``, which
        other ecosystems also use. Attachment is deliberately wider than
        detection here: prose under a dot root is linted whether or not the
        repository is typed ``antigravity``, because a rules file is agent
        context whichever tool ends up reading it.

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

    def antigravity_registry_files(self) -> List[Path]:
        """Conventional and inherited registries, including malformed documents."""
        roots = self.antigravity_customization_dirs()
        return [
            path
            for filename in REGISTRY_FILENAMES
            for path, _ in antigravity_discovery.iter_registries(
                self.root_path, roots, filename, is_excluded=self.is_path_excluded
            )
        ]

    def _antigravity_registry_plugin_roots(self) -> List[Path]:
        """Plugin roots a ``plugins.json`` names outside the install location."""
        return [
            path
            for path in antigravity_discovery.registry_plugin_roots(
                self.root_path, self.antigravity_registry_dirs(PLUGINS_REGISTRY)
            )
            if not self.is_path_excluded(path)
        ]

    def _antigravity_claim_set(self) -> Set[Path]:
        """Every resolved directory Antigravity claims, computed once.

        Manifest-backed install roots and registry claims survive every
        ``--type`` override. A forced ``antigravity-plugin`` additionally
        seeds manifest-less install directories for the requested check.
        """
        if self._antigravity_claims is None:
            claims = {r for p in self.antigravity_plugins if (r := safe_resolve(p)) is not None}
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
        # The roots union, because that is what skill discovery reads: a
        # registry-claimed plugin owns skills too, and an exclusion that
        # drops it has to take them with it.
        before = set(self.antigravity_plugin_roots())
        self._antigravity_claims = None
        self._antigravity_roots = None
        self._antigravity_workspace_roots = None
        if filtering:
            self.antigravity_plugins = self._discover_antigravity_plugins()
            self._prune_skills_of_dropped_antigravity_plugins(before)
        # Preserve the current claim set before a caller changes exclusions.
        # Skill discovery used these roots, so later pruning needs this snapshot.
        self.antigravity_plugin_roots()

    def _prune_skills_of_dropped_antigravity_plugins(self, before: Set[Path]) -> None:
        """Drop skills whose only owner left the set, as the Codex arm does.

        A plugin excluded by pattern leaves the roots union while its
        skills were discovered by the shared walk and stay in
        ``self.skills`` — where they attach as standalone nodes and keep
        linting the very content the exclusion removed. Compared against
        the same union ``_discover_skills`` reads, so the two cannot
        disagree about which plugin owns a skill.
        """
        dropped = before - set(self.antigravity_plugin_roots())
        if not dropped:
            return
        active = {
            r
            for p in (
                *self.plugins,
                *self.codex_plugins,
                *self.agent_plugins,
                *self.grok_plugin_roots(),
                *self.antigravity_plugin_roots(),
            )
            if (r := safe_resolve(p)) is not None
        }
        self.skills = [
            skill
            for skill in self.skills
            if not self._under_any(skill, dropped) or self._under_any(skill, active)
        ]
