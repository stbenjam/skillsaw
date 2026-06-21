"""Promptfoo eval-config format helpers.

Pure detection and file-reference resolution for promptfoo eval configs,
with no dependency on the rest of skillsaw.  Core modules (``context``,
``lint_tree``) use these to discover promptfoo configs while building the
lint tree; the promptfoo rule package re-exports them (under their legacy
underscore names) so existing rule code keeps working.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

# promptfoo eval configs are recognized by the presence of at least one of
# these top-level keys.
PROMPTFOO_KEYS = frozenset(
    {
        "providers",
        "prompts",
        "tests",
        "scenarios",
        "defaultTest",
        "evaluateOptions",
        "redteam",
        "targets",
    }
)


def is_promptfoo_config(data: object) -> bool:
    """True if data is a mapping with at least one promptfoo-specific key."""
    return isinstance(data, dict) and bool(PROMPTFOO_KEYS & set(data.keys()))


def resolve_file_ref(ref: str, config_dir: Path) -> Optional[Path]:
    """Resolve a file:// reference relative to config_dir.

    Returns the resolved path (which may or may not exist on disk).
    Returns None for glob patterns, non-YAML extensions, and remote URLs.
    """
    if not ref.startswith("file://"):
        if ref.startswith(("http://", "https://", "huggingface://")):
            return None
        raw = ref
    else:
        raw = ref[len("file://") :]

    if not raw:
        return None
    if any(c in raw for c in ("*", "?")):
        return None

    suffix = Path(raw).suffix.lower()
    if suffix not in (".yaml", ".yml"):
        return None

    return (config_dir / raw).resolve()


def extract_file_refs(data: dict) -> List[str]:
    """Extract string file references from a parsed promptfoo config's tests field."""
    refs: List[str] = []
    tests = data.get("tests")
    if isinstance(tests, str):
        refs.append(tests)
    elif isinstance(tests, list):
        for entry in tests:
            if isinstance(entry, str):
                refs.append(entry)
    return refs
