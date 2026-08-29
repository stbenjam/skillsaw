"""Stateful provenance for externally sourced repository content."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from .formats import skills_lock as skills_lock_format
from .paths import safe_is_dir, safe_resolve
from .utils import read_json_strict

if TYPE_CHECKING:
    from .discovery.detect import RepositoryScan


class RepositoryExternalContentMixin:
    """Cached external-content provenance for ``RepositoryContext``.

    Lock-managed skills and APM packages are the first producers. Keeping the
    policy in a dedicated stateful mixin leaves filesystem discovery pure and
    lets the lint tree consume one repository-wide authorship verdict.
    """

    if TYPE_CHECKING:
        root_path: Path
        has_apm: bool
        skills: List[Path]
        _externally_sourced_skill_roots: Optional[Set[Path]]
        _externally_sourced_roots: Optional[Set[Path]]

        def _repository_scan(self) -> "RepositoryScan": ...

        def is_path_excluded(self, path: Path) -> bool: ...

    def reset_external_content_provenance(self) -> None:
        """Invalidate provenance views after repository discovery changes."""
        self._externally_sourced_skill_roots = None
        self._externally_sourced_roots = None

    def skills_lock_files(self) -> List[Path]:
        """Return every non-excluded project ``skills-lock.json``."""
        lockfiles = self._repository_scan().skills_lock_files
        return [path for path in lockfiles if not self.is_path_excluded(path)]

    def externally_sourced_skill_roots(self) -> Set[Path]:
        """Resolved installed-skill roots owned by external lock entries.

        A project lock does not record which agent targets were selected or
        whether installation used copies or symlinks. Match its normalized
        install keys against discovered ``.../skills/<name>`` directories
        below the nearest lockfile project root. A nearer nested lock is a
        project boundary and takes precedence over an outer monorepo lock.

        Provenance reads every discovered non-vendored lockfile even when the
        lockfile itself is excluded from diagnostics. Excluding a manifest
        must not silently turn its installed dependencies into authored files
        that autofix may rewrite.
        """
        cached = getattr(self, "_externally_sourced_skill_roots", None)
        if cached is not None:
            return set(cached)

        repository_root = safe_resolve(self.root_path) or self.root_path
        projects: List[Tuple[Path, Set[str]]] = []
        for lockfile in self._repository_scan().skills_lock_files:
            data, error = read_json_strict(lockfile)
            if error or not isinstance(data, dict):
                continue
            entries = data.get("skills")
            if not isinstance(entries, dict):
                continue
            external_names = {
                skills_lock_format.sanitize_install_name(name)
                for name, entry in entries.items()
                if isinstance(name, str)
                and isinstance(entry, dict)
                and skills_lock_format.entry_is_external(
                    entry,
                    lock_root=lockfile.parent,
                    repository_root=repository_root,
                )
            }
            project_root = safe_resolve(lockfile.parent)
            # A valid nested lock is a project boundary even when none of its
            # entries are external (including an empty ``skills`` mapping).
            # Otherwise an outer monorepo lock can mislabel nested authored
            # content that happens to share an install name.
            if project_root is not None:
                projects.append((project_root, external_names))

        # Longest path first: the nearest nested lock owns the project.
        projects.sort(key=lambda item: len(item[0].parts), reverse=True)
        roots: Set[Path] = set()
        for skill_path in self.skills:
            resolved = safe_resolve(skill_path)
            if resolved is None:
                continue
            for project_root, external_names in projects:
                if not resolved.is_relative_to(project_root):
                    continue
                relative = resolved.relative_to(project_root)
                if (
                    len(relative.parts) >= 2
                    and relative.parts[-2] in {"skill", "skills"}
                    and skill_path.name in external_names
                ):
                    roots.add(resolved)
                break

        self._externally_sourced_skill_roots = roots
        return set(roots)

    def is_externally_sourced_skill(self, path: Path) -> bool:
        """Whether the installed skill at *path* has external provenance."""
        resolved = safe_resolve(path)
        return resolved is not None and (
            resolved in self.externally_sourced_skill_roots()
            or self.is_externally_sourced(resolved)
        )

    def externally_sourced_roots(self) -> Set[Path]:
        """Repository subtrees whose content comes from external sources.

        Lock-managed skill directories contribute precise roots. APM's
        ``apm_modules/`` is a package installation tree and contributes one
        subtree root; APM's compiled editor targets do not, because they are
        derived from repository-controlled ``.apm/`` sources and use the
        separate ``content_suppressed`` provenance instead.
        """
        cached = getattr(self, "_externally_sourced_roots", None)
        if cached is None:
            roots = set(self.externally_sourced_skill_roots())
            if self.has_apm:
                repository_root = safe_resolve(self.root_path) or self.root_path
                modules = safe_resolve(self.root_path / "apm_modules")
                if (
                    modules is not None
                    and modules.is_relative_to(repository_root)
                    and safe_is_dir(modules)
                ):
                    roots.add(modules)
            self._externally_sourced_roots = roots
            cached = roots
        return set(cached)

    def is_externally_sourced(self, path: Path) -> bool:
        """Whether *path* resolves within a known external-content root."""
        resolved = safe_resolve(path)
        if resolved is None:
            return False
        return any(
            resolved == root or resolved.is_relative_to(root)
            for root in self.externally_sourced_roots()
        )
