"""Stateful provenance for externally sourced repository content."""

from __future__ import annotations

import re

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Set, Tuple

from .formats import skills_lock as skills_lock_format
from .paths import (
    path_within_roots,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from .utils import read_json_strict

if TYPE_CHECKING:
    from .discovery.detect import RepositoryScan


#: ``[remote "origin"]`` url line of a ``.git/config``; only the url matters.
_GIT_REMOTE_URL_RE = re.compile(r"^\s*url\s*=\s*(\S+)", re.MULTILINE)
_GIT_ORIGIN_SECTION_RE = re.compile(r'\[remote "origin"\](.*?)(?=^\[|\Z)', re.DOTALL | re.MULTILINE)


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
        _external_path_verdict_cache: Dict[Path, bool]

        def _repository_scan(self) -> "RepositoryScan": ...

        def is_path_excluded(self, path: Path) -> bool: ...

    def reset_external_content_provenance(self) -> None:
        """Invalidate provenance views after repository discovery changes."""
        self._externally_sourced_skill_roots = None
        self._externally_sourced_roots = None
        self._external_path_verdict_cache = {}

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
        own_repository = self._github_repository_of(repository_root)
        projects: List[Tuple[Path, Set[str]]] = []
        for lockfile in self._repository_scan().skills_lock_files:
            project_root = safe_resolve(lockfile.parent)
            if project_root is None or not project_root.is_relative_to(repository_root):
                continue

            # The lexical lock location is a project boundary even when the
            # file is malformed, unreadable, or an escaping symlink. Failing
            # open prevents an outer monorepo lock from reclassifying nested
            # authored content. Only contained regular files are read.
            external_names: Set[str] = set()
            resolved_lockfile = safe_resolve(lockfile)
            if (
                resolved_lockfile is not None
                and resolved_lockfile.is_relative_to(project_root)
                and safe_is_file(resolved_lockfile)
            ):
                parsed_names = self._external_names_from_lock(
                    resolved_lockfile,
                    lock_root=project_root,
                    repository_root=repository_root,
                    own_repository=own_repository,
                )
                if parsed_names is not None:
                    external_names = parsed_names
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

    @staticmethod
    def _github_repository_of(root: Path) -> Optional[str]:
        """``owner/repo`` of *root*'s GitHub origin, without invoking Git.

        Linked worktrees keep a ``gitdir:`` pointer in ``.git`` and a
        ``commondir`` pointer in that metadata directory. Their origin lives
        in the common config, just as it does for the primary checkout.
        Missing or unreadable metadata and non-GitHub origins return ``None``.
        """
        git_dir = root / ".git"
        try:
            if safe_is_file(git_dir):
                pointer = git_dir.read_text(encoding="utf-8", errors="replace").strip()
                if not pointer.startswith("gitdir:") or not pointer[7:].strip():
                    return None
                git_dir = root / pointer[7:].strip()
            common_file = git_dir / "commondir"
            if safe_is_file(common_file):
                common = common_file.read_text(encoding="utf-8", errors="replace").strip()
                if not common:
                    return None
                git_dir = git_dir / common
            config = git_dir / "config"
            if not safe_is_file(config):
                return None
            text = config.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return None
        section = _GIT_ORIGIN_SECTION_RE.search(text)
        if section is None:
            return None
        url = _GIT_REMOTE_URL_RE.search(section.group(1))
        if url is None:
            return None
        return skills_lock_format.github_owner_repo(url.group(1))

    @staticmethod
    def _external_names_from_lock(
        lockfile: Path,
        *,
        lock_root: Path,
        repository_root: Path,
        own_repository: Optional[str] = None,
    ) -> Optional[Set[str]]:
        """Externally sourced install names, or ``None`` if malformed.

        An entry whose GitHub source is *own_repository* — the repository
        installing a skill from itself — is the repository's own authored
        content and is never external.
        """
        data, error = read_json_strict(lockfile)
        if error or not isinstance(data, dict):
            return None
        entries = data.get("skills")
        if not isinstance(entries, dict):
            return None
        return {
            skills_lock_format.sanitize_install_name(name)
            for name, entry in entries.items()
            if isinstance(name, str)
            and isinstance(entry, Mapping)
            and skills_lock_format.entry_has_valid_provenance(entry)
            and not skills_lock_format.entry_names_repository(entry, own_repository)
            and skills_lock_format.entry_is_external(
                entry,
                lock_root=lock_root,
                repository_root=repository_root,
            )
        }

    @staticmethod
    def _skill_root(path: Path) -> Optional[Path]:
        """Return the conventional installed-skill directory containing *path*."""
        for candidate in (path, *path.parents):
            if candidate.parent.name in {"skill", "skills"}:
                return candidate
        return None

    def _ancestor_lock_marks_external(self, path: Path) -> bool:
        """Resolve lock provenance when linting a dependency subtree directly."""
        skill_root = self._skill_root(path)
        if skill_root is None:
            return False

        for directory in skill_root.parents:
            lockfile = directory / "skills-lock.json"
            if not safe_exists(lockfile) and not safe_is_symlink(lockfile):
                if safe_exists(directory / ".git"):
                    break
                continue

            project_root = safe_resolve(directory)
            resolved_lockfile = safe_resolve(lockfile)
            if (
                project_root is None
                or resolved_lockfile is None
                or not resolved_lockfile.is_relative_to(project_root)
                or not safe_is_file(resolved_lockfile)
            ):
                return False
            external_names = self._external_names_from_lock(
                resolved_lockfile,
                lock_root=project_root,
                repository_root=project_root,
                own_repository=self._github_repository_of(project_root),
            )
            return (
                external_names is not None
                and skills_lock_format.sanitize_install_name(skill_root.name) in external_names
            )
        return False

    @staticmethod
    def _ancestor_apm_marks_external(path: Path) -> bool:
        """Resolve APM package provenance when linting below ``apm_modules``."""
        for candidate in (path, *path.parents):
            if candidate.name != "apm_modules":
                continue
            owner = candidate.parent
            return safe_is_dir(owner / ".apm") or safe_is_file(owner / "apm.yml")
        return False

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
        if path_within_roots(resolved, self.externally_sourced_roots()):
            return True
        cache = getattr(self, "_external_path_verdict_cache", None)
        if cache is None:
            cache = {}
            self._external_path_verdict_cache = cache
        if resolved not in cache:
            cache[resolved] = self._ancestor_apm_marks_external(
                resolved
            ) or self._ancestor_lock_marks_external(resolved)
        return cache[resolved]
