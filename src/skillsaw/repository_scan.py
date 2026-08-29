"""Cached stateful views over the repository's single discovery walk."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, TYPE_CHECKING, Tuple

from .discovery import detect as detect_discovery

if TYPE_CHECKING:
    from .discovery.detect import RepositoryScan


class RepositoryScanMixin:
    """Repository scan orchestration shared by format-specific mixins."""

    _INSTRUCTION_FILENAMES: Tuple[str, ...]

    if TYPE_CHECKING:
        root_path: Path
        instruction_files: List[Path]
        _scan: Optional[RepositoryScan]

        def is_path_excluded(self, path: Path) -> bool: ...

    def _discover_instruction_files(self) -> List[Path]:
        """Discover root and nested instruction files read by supported tools.

        Includes root conventions, Copilot ``*.instructions.md`` files, and
        Devin's documented names at nested project levels. The work shares
        one filesystem walk with :meth:`agent_tool_dirs`.
        """
        return list(self._repository_scan().instruction_files)

    def _repository_scan(self) -> RepositoryScan:
        """Return the cached single-pass walk of the repository."""
        if self._scan is None:
            self._scan = detect_discovery.scan_repository(
                self.root_path, self._INSTRUCTION_FILENAMES
            )
        return self._scan

    def agent_tool_dirs(self, name: str) -> List[Path]:
        """Return every non-excluded directory called *name* in the repository.

        Cursor (``.cursor``), Copilot/VS Code (``.github``), Cline
        (``.clinerules``), Devin (``.devin``/``.windsurf``), and OpenCode
        (``.opencode``) all read customizations from the nearest enclosing
        directory, so a monorepo package may carry its own alongside the root.
        """
        return [
            path
            for path in self._repository_scan().tool_dirs.get(name, ())
            if not self.is_path_excluded(path)
        ]

    def legacy_editor_files(self, name: str) -> List[Path]:
        """Every non-excluded *name* legacy editor file in the repository."""
        return [
            path
            for path in self._repository_scan().legacy_editor_files.get(name, ())
            if not self.is_path_excluded(path)
        ]

    def _detect_formats(self) -> set[str]:
        return detect_discovery.instruction_formats(
            self.root_path,
            self.instruction_files,
            self.is_path_excluded,
            self._repository_scan().tool_dirs,
            self._repository_scan().legacy_editor_files,
            self._repository_scan().skills_lock_files,
        )

    #: Alias for the one definition in discovery. Two copies of "which
    #: directories does a walk prune" are how a checkout starts being walked
    #: differently by two callers that both believe they agree.
    _WALK_SKIP_DIRS = detect_discovery.WALK_SKIP_DIRS
