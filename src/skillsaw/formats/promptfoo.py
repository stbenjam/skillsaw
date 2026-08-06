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

from skillsaw.paths import safe_resolve

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


def resolve_file_ref(ref: str, config_dir: Path, root: Optional[Path] = None) -> Optional[Path]:
    """Resolve a file:// reference relative to config_dir.

    Returns the resolved path (which may or may not exist on disk).
    Returns None for glob patterns, non-YAML extensions, remote URLs, and
    paths that cannot be safely resolved.

    When ``root`` is given, refs whose resolved path (symlinks followed)
    falls outside of it are rejected and None is returned — a config must
    not pull files from outside the repository into the lint tree.
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

    # Resolution failure means the ref cannot safely become a lint-tree node.
    # Returning the raw path would only defer the same hostile input to an
    # unsafe filesystem predicate in a downstream caller.
    resolved = safe_resolve(config_dir / raw)
    if resolved is None:
        return None

    # Disallow escaping the repo root (mirrors
    # context._resolve_plugin_source).  root is re-resolved because this
    # helper is standalone and callers may pass an unresolved root.
    if root is not None:
        resolved_root = safe_resolve(root)
        if resolved_root is None or not resolved.is_relative_to(resolved_root):
            return None

    return resolved


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
