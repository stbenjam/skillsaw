"""State-free filesystem discovery for OpenCode configured instructions."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterator, Set, Tuple

from skillsaw.paths import (
    contained_resolve,
    has_parent_traversal,
    is_absolute_path,
    safe_is_symlink,
)


def contained_instruction_glob(
    repo_root: Path,
    glob_base: Path,
    pattern: str,
    is_excluded: Callable[[Path], bool],
) -> Iterator[Path]:
    """Yield matches without walking outside *repo_root* or through links."""
    if is_absolute_path(pattern) or has_parent_traversal(pattern):
        return

    parts = tuple(part for part in Path(pattern).parts if part not in ("", "."))
    visited: Set[Tuple[Path, int]] = set()

    def _descend(directory: Path, index: int) -> Iterator[Path]:
        state = (directory, index)
        if state in visited:
            return
        visited.add(state)

        # Check before scandir: resolving and rejecting directory symlinks
        # prevents a repository-controlled pattern from enumerating elsewhere.
        if (
            contained_resolve(directory, repo_root) != directory
            or safe_is_symlink(directory)
            or is_excluded(directory)
        ):
            return

        if index == len(parts):
            yield directory
            return

        component = parts[index]
        if component == "**":
            yield from _descend(directory, index + 1)

        with os.scandir(directory) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)

        if component == "**":
            for entry in entries:
                try:
                    is_real_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_real_dir:
                    yield from _descend(directory / entry.name, index)
            return

        for entry in entries:
            if not fnmatch.fnmatch(entry.name, component):
                continue
            candidate = directory / entry.name
            if index + 1 == len(parts):
                yield candidate
                continue
            try:
                is_real_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_real_dir:
                yield from _descend(candidate, index + 1)

    yield from _descend(glob_base, 0)
