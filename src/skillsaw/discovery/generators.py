"""State-free discovery of the conventional, authored generator rule trees."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from skillsaw.discovery.excludes import is_root_or_ancestor_excluded
from skillsaw.paths import contained_resolve

GENERATOR_DIR_NAMES = frozenset({".ruler", ".rulesync"})


@dataclass(frozen=True)
class GeneratorProject:
    generator: str
    root: Path
    source_dir: Path
    rules: Tuple[Path, ...]
    config: Optional[Path]


def discover_projects(
    root: Path,
    directories: Iterable[Path],
    configs: Iterable[Path],
    *,
    resolve: Callable[[Path], Optional[Path]],
    is_excluded: Callable[[Path], bool],
) -> Tuple[GeneratorProject, ...]:
    """Read local rules only; never load home config, fetch, or run a generator.

    Symlink files are accepted only inside their source tree; directory links
    are not followed. Ruler's separately propagated skills/agents and
    Rulesync's fetched .curated tree are outside this authored subset.
    """
    candidates = set(directories)
    candidates.update(p.parent / ".rulesync" for p in configs)
    projects = []
    for directory in sorted(candidates):
        if contained_resolve(directory.parent, root, resolve) is None:
            continue
        ruler = directory.name == ".ruler"
        source = directory if ruler else directory / "rules"
        source_resolved = contained_resolve(source, root, resolve)
        files = []
        # Rulesync's config is a sibling of its source tree. Excluding the
        # source directory must not hide that config or its consumer project.
        if (
            source_resolved is not None
            and not source.is_symlink()
            and not directory.is_symlink()
            and not is_root_or_ancestor_excluded(source, root, is_excluded)
        ):
            seen = set()
            for here, dirs, names in os.walk(source):
                base = Path(here)
                dirs[:] = sorted(
                    name
                    for name in dirs
                    if (ruler or not name.startswith("."))
                    and not (ruler and base == source and name in {"skills", "agents"})
                    and not is_excluded(base / name)
                )
                for name in sorted(names):
                    path = base / name
                    if not name.endswith(".md") or (not ruler and name.startswith(".")):
                        continue
                    target = contained_resolve(path, source_resolved, resolve)
                    if (
                        target is not None
                        and target not in seen
                        and target.is_file()
                        and not is_root_or_ancestor_excluded(path, root, is_excluded)
                        and not is_root_or_ancestor_excluded(target, root, is_excluded)
                    ):
                        seen.add(target)
                        files.append(path)
        config = directory / "ruler.toml" if ruler else directory.parent / "rulesync.jsonc"
        if (
            contained_resolve(config, root, resolve) is None
            or not config.is_file()
            or is_root_or_ancestor_excluded(config, root, is_excluded)
        ):
            config = None
        if files or config is not None:
            projects.append(
                GeneratorProject(
                    "ruler" if ruler else "rulesync",
                    directory.parent,
                    source,
                    tuple(sorted(files)),
                    config,
                )
            )
    return tuple(projects)
