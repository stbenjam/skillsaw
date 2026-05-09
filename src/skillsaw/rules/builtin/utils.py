"""Shared utilities for builtin rules."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml


@lru_cache(maxsize=512)
def read_text(file_path: Path) -> Optional[str]:
    """Cached file read. Returns None on I/O or encoding errors."""
    try:
        return file_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return None


def invalidate_read_caches():
    """Clear all file-reading caches. Call after modifying files on disk."""
    read_text.cache_clear()
    read_json.cache_clear()
    frontmatter_key_line.cache_clear()
    heading_line.cache_clear()


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


_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?\n)---[ \t]*\n?", re.DOTALL)


def parse_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_after_frontmatter).
    If no valid frontmatter is found, returns (None, original_content).
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None, content
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, content
    if not isinstance(data, dict):
        return None, content
    body = content[m.end() :]
    return data, body


def extract_section(content: str, heading: str, level: int = 2) -> str:
    """Extract content under a markdown heading, up to the next heading of same or higher level."""
    prefix = "#" * level
    pattern = re.compile(
        rf"^{prefix}[ \t]+{re.escape(heading)}[ \t]*$\r?\n?(.*?)(?=^#{{{1},{level}}}[ \t]|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(content)
    return m.group(1).strip() if m else ""


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
