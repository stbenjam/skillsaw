"""Shared validation helpers for Codex plugin rules."""

from pathlib import PurePosixPath, PureWindowsPath
import re

from skillsaw.context import RepositoryType

CODEX_PLUGIN_REPO_TYPES = {
    RepositoryType.CODEX_PLUGIN,
    RepositoryType.CODEX_MARKETPLACE,
}
CODEX_MARKETPLACE_REPO_TYPES = {RepositoryType.CODEX_MARKETPLACE}

KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def is_absolute_path(path: str) -> bool:
    """Return true for POSIX, drive-qualified, and UNC absolute paths."""
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def has_parent_traversal(path: str) -> bool:
    """Return true when *path* contains a parent-directory component."""
    return ".." in path.replace("\\", "/").split("/")


def relative_path_error(path: object) -> str | None:
    """Explain why a Codex manifest path is unsafe, or return ``None``."""
    if not isinstance(path, str) or not path:
        return "must be a non-empty string"
    if is_absolute_path(path):
        return "must be relative to the plugin or marketplace root"
    if has_parent_traversal(path):
        return "must stay inside the plugin or marketplace root"
    if not path.startswith("./"):
        return "must start with './'"
    return None
