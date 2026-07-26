"""OpenAI Codex plugin-format helpers.

Pure functions over Codex manifest and marketplace values, with no
dependency on the rest of skillsaw. ``context`` uses them while building
the lint tree, and re-exports ``codex_local_source_path`` so the rule
package's existing import keeps working.

Kept out of ``context.py`` deliberately: these need no repository state,
and the discovery methods that do are large enough on their own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def codex_local_source_path(source: Any) -> Optional[str]:
    """Relative path of a Codex marketplace entry's *local* source.

    Codex accepts either an object (``{"source": "local", "path": "./x"}``)
    or, for local entries only, a bare path string. Returns ``None`` for
    remote sources (``url``, ``git-subdir``, ``npm``) and malformed entries,
    which have no local directory to resolve.
    """
    if isinstance(source, str):
        return source or None
    if isinstance(source, dict) and source.get("source") == "local":
        path = source.get("path")
        if isinstance(path, str) and path:
            return path
    return None


def safe_resolve(path: Path) -> Optional[Path]:
    """``path.resolve()``, or ``None`` when the path cannot be resolved.

    Discovery runs while ``RepositoryContext`` is being constructed, before
    any rule can report anything, and it resolves strings taken straight
    out of a manifest. ``Path.resolve()`` raises ``ValueError`` on an
    embedded NUL and ``OSError`` on a symlink loop or an unreadable
    parent — either one would abort the whole lint instead of producing
    the violation the manifest deserves. Returning ``None`` drops the
    candidate from discovery and leaves the reporting to the rules.
    """
    try:
        return path.resolve()
    except (OSError, ValueError):
        return None


def inline_documents(declared: Any, key: str) -> List[Dict[str, Any]]:
    """One document per inline object in a Codex manifest field.

    ``hooks`` and ``mcpServers`` both accept "a single path, an array of
    paths, an inline object, or an array of inline objects". This unpacks
    the object forms, normalising each to ``{key: <body>}`` so it reads
    like the file the field could have named instead — a nested *key* is
    used as-is, and a bare body is wrapped.

    One document per object, never a merge. Merging read tidier but had to
    discard occurrences when an array repeated an event or a server name,
    and either loss hides a defect: the dropped occurrence is never
    validated, and if the dropped one was the valid one its commands never
    reach the security rules.
    """
    candidates = declared if isinstance(declared, list) else [declared]
    documents: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        nested = item.get(key)
        documents.append({key: nested if isinstance(nested, dict) else item})
    return documents
