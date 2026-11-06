"""State-free resolution of repository-authored Kiro file references."""

from pathlib import Path
from typing import Callable, Optional

from skillsaw.discovery.excludes import is_root_or_ancestor_excluded
from skillsaw.paths import contained_resolve, is_absolute_path


def local_reference(
    text: str,
    base: Path,
    root: Path,
    *,
    resolve: Callable[[Path], Optional[Path]],
    is_excluded: Callable[[Path], bool],
) -> Optional[Path]:
    """Resolve a literal relative path, including a missing contained target.

    No HOME expansion, interpolation, glob expansion, or machine-absolute
    paths: these depend on state outside the repository. Resolving a path
    proves containment before any caller reads its contents.
    """
    if (
        not text
        or text.startswith("~")
        or is_absolute_path(text)
        or any(char in text for char in "*?[]{}$\x00")
    ):
        return None
    path = base / text
    resolved = contained_resolve(path, root, resolve)
    if resolved is None or is_root_or_ancestor_excluded(path, root, is_excluded):
        return None
    if is_root_or_ancestor_excluded(resolved, root, is_excluded):
        return None
    return resolved
