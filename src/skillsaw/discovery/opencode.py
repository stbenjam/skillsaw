"""State-free filesystem discovery for OpenCode configured instructions."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Set, Tuple

from skillsaw.paths import (
    contained_resolve,
    has_parent_traversal,
    is_absolute_path,
    safe_is_symlink,
)


def contained_instruction_globs(
    repo_root: Path,
    glob_base: Path,
    patterns: Iterable[str],
    is_excluded: Callable[[Path], bool],
) -> Iterator[Tuple[int, Path]]:
    """Yield each pattern's matches from one shared, contained traversal.

    The integer in each result is the pattern's input index. A scan failure
    invalidates only patterns that would have visited that directory, matching
    the former one-pattern-at-a-time behavior without repeating ``scandir``.
    """
    pattern_parts: List[Tuple[str, ...]] = []
    active: Set[Tuple[int, int]] = set()
    for pattern_index, pattern in enumerate(patterns):
        if is_absolute_path(pattern) or has_parent_traversal(pattern):
            pattern_parts.append(())
            continue
        parts = tuple(part for part in Path(pattern).parts if part not in ("", "."))
        pattern_parts.append(parts)
        active.add((pattern_index, 0))

    matches: List[Set[Path]] = [set() for _parts in pattern_parts]
    failed: Set[int] = set()

    def _descend(directory: Path, states: Set[Tuple[int, int]]) -> None:
        states = {state for state in states if state[0] not in failed}
        if not states:
            return

        # Check before scandir: resolving and rejecting directory symlinks
        # prevents a repository-controlled pattern from enumerating elsewhere.
        if (
            contained_resolve(directory, repo_root) != directory
            or safe_is_symlink(directory)
            or is_excluded(directory)
        ):
            return

        # ``**`` may consume zero directories. Close those transitions before
        # scanning, retaining the original state so it can consume a child.
        closure = set(states)
        pending = list(states)
        while pending:
            pattern_index, part_index = pending.pop()
            parts = pattern_parts[pattern_index]
            if part_index == len(parts):
                matches[pattern_index].add(directory)
                continue
            if parts[part_index] == "**":
                next_state = (pattern_index, part_index + 1)
                if next_state not in closure:
                    closure.add(next_state)
                    pending.append(next_state)

        scanning_patterns = {
            pattern_index
            for pattern_index, part_index in closure
            if part_index < len(pattern_parts[pattern_index])
        }
        if not scanning_patterns:
            return

        try:
            with os.scandir(directory) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except (OSError, ValueError):
            failed.update(scanning_patterns)
            for pattern_index in scanning_patterns:
                matches[pattern_index].clear()
            return

        for entry in entries:
            candidate = directory / entry.name
            child_states: Set[Tuple[int, int]] = set()
            for pattern_index, part_index in closure:
                if pattern_index in failed:
                    continue
                parts = pattern_parts[pattern_index]
                if part_index == len(parts):
                    continue
                component = parts[part_index]
                if component == "**":
                    child_states.add((pattern_index, part_index))
                    continue
                if not fnmatch.fnmatch(entry.name, component):
                    continue
                if part_index + 1 == len(parts):
                    matches[pattern_index].add(candidate)
                else:
                    child_states.add((pattern_index, part_index + 1))

            if not child_states:
                continue
            try:
                is_real_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_real_dir:
                _descend(candidate, child_states)

    _descend(glob_base, active)
    for pattern_index, pattern_matches in enumerate(matches):
        if pattern_index in failed:
            continue
        for match in sorted(pattern_matches):
            yield pattern_index, match
