"""Vocabulary for Vercel skills CLI project lockfiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

from skillsaw.paths import safe_resolve

CURRENT_VERSION = 1

# Values produced by the current project-lock writer, plus ``download`` from
# the source parser so validation remains forward-compatible if that source
# begins participating in lockfile persistence.
SOURCE_TYPES = frozenset(
    {
        "download",
        "git",
        "github",
        "gitlab",
        "local",
        "node_modules",
        "well-known",
    }
)

COMPUTED_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
WELL_KNOWN_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
UNSAFE_INSTALL_NAME_RE = re.compile(r"[^a-z0-9._]+")
INSTALL_NAME_EDGE_RE = re.compile(r"^[.\-]+|[.\-]+$")


def is_absolute_path(value: str) -> bool:
    """Whether *value* is absolute in POSIX, Windows drive, or UNC syntax."""
    return value.startswith(("/", "\\\\", "//")) or bool(WINDOWS_ABSOLUTE_RE.match(value))


def has_parent_segment(value: str) -> bool:
    """Whether a portable path contains a ``..`` traversal segment."""
    return ".." in value.replace("\\", "/").split("/")


def is_bare_git_source(value: str) -> bool:
    """Mirror the skills CLI's shorthand test for git/gitlab sources."""
    return ":" not in value and not value.startswith((".", "/"))


def sanitize_install_name(value: str) -> str:
    """Mirror the skills CLI directory-name normalization for an install key."""
    sanitized = UNSAFE_INSTALL_NAME_RE.sub("-", value.lower())
    sanitized = INSTALL_NAME_EDGE_RE.sub("", sanitized)
    return sanitized[:255] or "unnamed-skill"


def entry_has_valid_provenance(entry: Mapping[str, object]) -> bool:
    """Whether an entry has enough valid evidence to assign ownership."""
    source = entry.get("source")
    source_type = entry.get("sourceType")
    computed_hash = entry.get("computedHash")
    return (
        isinstance(source, str)
        and bool(source.strip())
        and isinstance(source_type, str)
        and bool(source_type.strip())
        and isinstance(computed_hash, str)
        and bool(COMPUTED_HASH_RE.fullmatch(computed_hash))
    )


def entry_is_external(
    entry: Mapping[str, object], *, lock_root: Path, repository_root: Path
) -> bool:
    """Whether a lock entry's source is outside the repository under lint.

    Every remote, registry, package-manager, or unknown source is external.
    A ``local`` source is repository-owned only when its resolved path stays
    inside the lint root; a symlink escape and a path whose containment cannot
    be established both fail closed as external.
    """
    if entry.get("sourceType") != "local":
        return True

    source = entry.get("source")
    if not isinstance(source, str) or not source.strip():
        return True

    # A Windows absolute path cannot resolve meaningfully on POSIX. It is
    # external either way; POSIX absolute paths can still point inside the
    # lint root and are checked normally below.
    if WINDOWS_ABSOLUTE_RE.match(source) or source.startswith(("\\\\", "//")):
        return True
    normalized = source.replace("\\", "/")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = lock_root / candidate
    resolved = safe_resolve(candidate)
    return resolved is None or not resolved.is_relative_to(repository_root)
