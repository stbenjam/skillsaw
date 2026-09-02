"""Vocabulary for Vercel skills CLI project lockfiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Optional

from skillsaw.paths import is_absolute_path, safe_resolve

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
UNSAFE_INSTALL_NAME_RE = re.compile(r"[^a-z0-9._]+")
INSTALL_NAME_EDGE_RE = re.compile(r"^[.\-]+|[.\-]+$")


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
    if is_absolute_path(source) and not (source.startswith("/") and not source.startswith("//")):
        return True
    normalized = source.replace("\\", "/")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = lock_root / candidate
    resolved = safe_resolve(candidate)
    return resolved is None or not resolved.is_relative_to(repository_root)


_GITHUB_SOURCE_PREFIXES = (
    "https://github.com/",
    "http://github.com/",
    "ssh://git@github.com/",
    "git@github.com:",
    "github:",
    "github.com/",
)


def github_owner_repo(source: str) -> Optional[str]:
    """``owner/repo`` (lower-cased) for a GitHub source in any spelling the
    CLI accepts — bare ``owner/repo``, ``github:owner/repo``, an HTTPS or SSH
    URL, with or without ``.git`` and a ``#ref``/``@ref`` suffix. ``None``
    for anything else."""
    value = source.strip()
    lowered = value.lower()
    for prefix in _GITHUB_SOURCE_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    else:
        if "://" in value or value.startswith("git@"):
            return None
    value = value.split("#", 1)[0].split("@", 1)[0].strip("/")
    parts = value.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1] or parts[0].startswith("."):
        return None
    repo = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    return f"{parts[0]}/{repo}".lower()


def entry_names_repository(entry: Mapping[str, object], owner_repo: Optional[str]) -> bool:
    """Whether a GitHub lock entry's source is *owner_repo* — the repository
    under lint installing a skill from itself.

    A repository that publishes a skill and also installs it with
    ``npx skills add <its own repo>`` records its own coordinates in the
    lock. That entry describes the repository's own authored content, not
    an external dependency, so provenance must not mark the authored copy
    external and refuse to fix it.
    """
    if owner_repo is None or entry.get("sourceType") != "github":
        return False
    source = entry.get("source")
    if not isinstance(source, str):
        return False
    return github_owner_repo(source) == owner_repo
