"""Stateful MCP Registry publisher-metadata discovery views.

The repository walk remains state-free in discovery.detect. This mixin is the
small stateful seam that filters and caches its server.json and package.json
results for RepositoryContext.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from .formats.mcp_registry import is_mcp_registry_server
from .paths import contained_resolve, safe_is_file, safe_resolve
from .utils import read_json

if TYPE_CHECKING:
    from .discovery.detect import RepositoryScan


class RepositoryMcpRegistryMixin:
    """Cached MCP Registry discovery behavior for RepositoryContext."""

    if TYPE_CHECKING:
        root_path: Path
        _mcp_registry_paths: Optional[List[Path]]
        _mcp_registry_forced: bool

        def _repository_scan(self) -> RepositoryScan: ...

        def is_path_excluded(self, path: Path) -> bool: ...

    def _init_mcp_registry(self, forced: bool) -> None:
        """Initialize Registry state without growing the context orchestrator."""
        self._mcp_registry_paths = None
        self._mcp_registry_forced = forced

    def mcp_registry_server_paths(self) -> List[Path]:
        """Return high-confidence, contained Registry server.json documents.

        A filename alone is ambiguous. Automatic discovery requires either a
        canonical MCP Registry schema URL or the registry's distinctive
        identity plus package/remote shape. --type mcp-registry is the escape
        hatch for malformed documents that cannot identify themselves.
        """
        if self._mcp_registry_paths is None:
            paths: List[Path] = []
            root = safe_resolve(self.root_path)
            if root is None:
                return []
            for path in self._repository_scan().mcp_registry_files:
                if self.is_path_excluded(path):
                    continue
                resolved = contained_resolve(path, root)
                if resolved is None or not safe_is_file(resolved):
                    continue
                if self._mcp_registry_forced:
                    paths.append(path)
                    continue
                data, error = read_json(resolved)
                if error is None and is_mcp_registry_server(data):
                    paths.append(path)
            self._mcp_registry_paths = paths
        return list(self._mcp_registry_paths)

    def package_json_paths(self) -> List[Path]:
        """Return contained, non-vendored, non-excluded package manifests."""
        root = safe_resolve(self.root_path)
        if root is None:
            return []
        paths: List[Path] = []
        for path in self._repository_scan().package_json_files:
            if self.is_path_excluded(path):
                continue
            resolved = contained_resolve(path, root)
            if resolved is not None and safe_is_file(resolved):
                paths.append(path)
        return paths
