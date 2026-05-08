"""Shared utilities for builtin rules."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple


@lru_cache(maxsize=512)
def read_text(file_path: Path) -> Optional[str]:
    """Cached file read. Returns None on I/O or encoding errors."""
    try:
        return file_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return None


@lru_cache(maxsize=512)
def read_json(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Cached JSON file read. Returns (data, error)."""
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        return None, str(e)


@lru_cache(maxsize=512)
def frontmatter_key_line(file_path: Path, key: str) -> Optional[int]:
    """Find the line number of a top-level key in YAML frontmatter."""
    content = read_text(file_path)
    if content is None:
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    in_frontmatter = False
    for i, line in enumerate(content.splitlines(), 1):
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break
        if in_frontmatter and pattern.match(line):
            return i
    return None


@lru_cache(maxsize=512)
def heading_line(file_path: Path, heading: str, level: int = 2) -> Optional[int]:
    """Find the line number of a markdown heading."""
    content = read_text(file_path)
    if content is None:
        return None
    prefix = "#" * level
    pattern = re.compile(rf"^{prefix}\s+{re.escape(heading)}\s*$")
    for i, line in enumerate(content.splitlines(), 1):
        if pattern.match(line):
            return i
    return None
