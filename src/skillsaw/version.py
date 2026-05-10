"""Version string parsing utilities."""

import re
from typing import Tuple


def parse_version(v: str) -> Tuple[int, ...]:
    """Parse a version string like '1.2.3' into a tuple of ints.

    Strips a leading 'v'/'V' prefix and ignores pre-release suffixes
    (e.g. '-beta', '-rc1').  Raises :class:`ValueError` with a
    human-readable message when the string cannot be parsed.
    """
    original = v
    v = v.strip()
    v = re.sub(r"^[vV]", "", v)
    v = re.split(r"[-+]", v, maxsplit=1)[0]
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError as err:
        raise ValueError(
            f"Invalid version string '{original}': expected a numeric "
            f"version like '1.0.0', got non-numeric component"
        ) from err


def is_valid_semver(v: str) -> bool:
    """Check if a string is a valid semver version (X.Y.Z with optional pre-release/build)."""
    return bool(re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?(\+[a-zA-Z0-9.-]+)?$", str(v)))
