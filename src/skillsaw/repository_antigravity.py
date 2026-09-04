"""Stateful Antigravity plugin and configuration discovery views.

Discovery gathers Antigravity filesystem evidence without state. This mixin is
the stateful seam that caches it for ``RepositoryContext`` and applies the
``--type`` gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, List, Optional, Set

from .discovery import antigravity as antigravity_discovery
from .formats.antigravity import ANTIGRAVITY_CONFIG_DIR_NAMES
from .paths import safe_resolve
from .repository_types import RepositoryType

_ANTIGRAVITY_TYPES = frozenset({RepositoryType.ANTIGRAVITY_PLUGIN})


class RepositoryAntigravityMixin:
    """Cached Antigravity plugin and configuration discovery behavior for RepositoryContext."""

    if TYPE_CHECKING:
        root_path: Path
        plugins: List[Path]
        codex_plugins: List[Path]
        agent_plugins: List[Path]
        skills: List[Path]
        grok_plugins: List[Path]
        antigravity_plugins: List[Path]
        _antigravity_config_paths: Optional[List[Path]]
        _antigravity_claims: Optional[Set[Path]]
        _antigravity_discovery_enabled: bool
        _antigravity_plugin_forced: bool

        def agent_tool_dirs(self, name: str) -> List[Path]: ...

        def is_path_excluded(self, path: Path) -> bool: ...

    def _init_antigravity(self, repo_types: Optional[Iterable[RepositoryType]]) -> None:
        """Set up Antigravity caches and the ``--type`` gate, then discover plugins."""
        selected = None
        if repo_types is not None:
            selected_types = set(repo_types)
            selected = bool(selected_types & _ANTIGRAVITY_TYPES)
            self._antigravity_plugin_forced = RepositoryType.ANTIGRAVITY_PLUGIN in selected_types
        else:
            self._antigravity_plugin_forced = False
        self._antigravity_discovery_enabled = selected is not False
        self._antigravity_config_paths = None
        self._antigravity_claims = None
        self.antigravity_plugins = (
            self._discover_antigravity_plugins() if self._antigravity_discovery_enabled else []
        )

    def antigravity_config_files(self) -> List[Path]:
        """Discovered Antigravity configuration files."""
        if self._antigravity_config_paths is None:
            tool_dirs = {d: self.agent_tool_dirs(d) for d in ANTIGRAVITY_CONFIG_DIR_NAMES}
            configs = antigravity_discovery.discover_antigravity_configs(
                self.root_path, tool_dirs=tool_dirs
            )
            self._antigravity_config_paths = [p for p in configs if not self.is_path_excluded(p)]
        return self._antigravity_config_paths

    def _discover_antigravity_plugins(self) -> List[Path]:
        """Directories declaring an Antigravity plugin."""
        return [
            path
            for path in antigravity_discovery.discover_antigravity_plugins(
                self.root_path,
                forced=self._antigravity_plugin_forced,
            )
            if not self.is_path_excluded(path)
        ]

    def _antigravity_claim_set(self) -> Set[Path]:
        """Every resolved directory Antigravity claims, computed once per context."""
        if self._antigravity_claims is None:
            self._antigravity_claims = {
                r for r in (safe_resolve(p) for p in self.antigravity_plugins) if r is not None
            }
        return self._antigravity_claims

    def _reset_antigravity_caches(self, filtering: bool = False) -> None:
        """Drop every cached Antigravity view; re-run discovery when excludes narrowed."""
        self._antigravity_config_paths = None
        self._antigravity_claims = None
        if filtering and self._antigravity_discovery_enabled:
            self.antigravity_plugins = self._discover_antigravity_plugins()
