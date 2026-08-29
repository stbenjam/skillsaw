"""Vocabulary for Vercel skills CLI project lockfiles."""

from __future__ import annotations

import re

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


def is_absolute_path(value: str) -> bool:
    """Whether *value* is absolute in POSIX, Windows drive, or UNC syntax."""
    return value.startswith(("/", "\\\\", "//")) or bool(WINDOWS_ABSOLUTE_RE.match(value))


def has_parent_segment(value: str) -> bool:
    """Whether a portable path contains a ``..`` traversal segment."""
    return ".." in value.replace("\\", "/").split("/")


def is_bare_git_source(value: str) -> bool:
    """Mirror the skills CLI's shorthand test for git/gitlab sources."""
    return ":" not in value and not value.startswith((".", "/"))
