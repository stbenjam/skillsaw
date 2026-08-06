"""OpenAI Codex plugin-format helpers.

State-free readers over Codex manifest and marketplace values — they need
only a plugin directory, never a ``RepositoryContext``. ``context`` uses
them while building the lint tree; rules and the docs extractor import
them directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.utils import read_json


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


REMOTE_SOURCE_TYPES = frozenset({"url", "git-subdir", "npm"})


def is_remote_source(source: Any) -> bool:
    """Whether *source* is one of Codex's remote source types.

    Deliberately narrower than "not local": a malformed entry (``source:
    42``, ``{"source": "local"}`` with no path, a typo'd type) resolves to
    no local directory *and* names nothing installable, so it is neither.
    Callers that treat every non-local source as remote credit those
    entries with a registration they do not provide.
    """
    if not isinstance(source, dict):
        return False
    # A JSON value need not be hashable, and ``{"source": []}`` against a
    # frozenset raises TypeError — which becomes a rule-execution-error and
    # aborts the rule instead of letting the validity rule report the shape.
    kind = source.get("source")
    return isinstance(kind, str) and kind in REMOTE_SOURCE_TYPES


def inline_documents(declared: Any, key: str) -> List[Dict[str, Any]]:
    """One document per inline object in a Codex manifest field.

    ``hooks`` and ``mcpServers`` both accept "a single path, an array of
    paths, an inline object, or an array of inline objects". This unpacks
    the object forms, normalising each to ``{key: <body>}`` so it reads
    like the file the field could have named instead — a nested *key* is
    used as-is, and a bare body is wrapped.

    One document per object, NEVER a merge: merging must discard
    occurrences when an array repeats an event or server name, and the
    dropped occurrence is either never validated or never reaches the
    security rules with its commands.
    """
    candidates = declared if isinstance(declared, list) else [declared]
    documents: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        nested = item.get(key)
        # Only unwrap when the wrapper key is the *only* key. A bare map may
        # legitimately hold a server or event named the same as the wrapper,
        # and unwrapping on its presence alone would silently discard every
        # sibling — including ones the security rules need to see.
        wrapped = isinstance(nested, dict) and len(item) == 1
        documents.append({key: nested if wrapped else item})
    return documents


# The reserved manifest location. Kept here rather than on the context so
# the readers below need no repository state at all.
CODEX_PLUGIN_MANIFEST = (".codex-plugin", "plugin.json")


def codex_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """A Codex plugin's parsed manifest, or ``{}`` when absent or unparseable.

    Uses the shared cached reader: strips a UTF-8 BOM, and repeated reads
    cost nothing.
    """
    data, error = read_json(plugin_dir.joinpath(*CODEX_PLUGIN_MANIFEST))
    return data if not error and isinstance(data, dict) else {}


def codex_plugin_name(plugin_dir: Path) -> str:
    """Name a Codex plugin declares, falling back to its directory name."""
    name = codex_manifest(plugin_dir).get("name")
    return name if isinstance(name, str) and name else plugin_dir.name


def codex_declared_paths(plugin_dir: Path, field: str, want_dir: bool) -> List[Path]:
    """Contained paths a Codex manifest names in *field*.

    Three manifest fields — ``hooks``, ``skills`` and ``mcpServers`` —
    share one shape: "a single path, an array of paths, an inline object,
    or an array of inline objects". This resolves the path forms; the
    object forms are read by :func:`inline_documents`. Paths escaping the
    plugin root are dropped — ``codex-plugin-json-valid`` reports them, and
    the lint tree must not follow them out of the plugin.
    """
    declared = codex_manifest(plugin_dir).get(field)
    # One level only. The field permits a path or an array of paths, so a
    # nested array is invalid — and flattening it here would diverge from
    # codex-plugin-json-valid, which reports what it can reach.
    candidates = declared if isinstance(declared, list) else [declared]
    root = safe_resolve(plugin_dir)
    if root is None:
        return []
    found: List[Path] = []
    for item in candidates:
        if not isinstance(item, str) or not item:
            continue
        candidate = contained_resolve(plugin_dir / item, root)
        if candidate is None:
            continue
        # ``"skills": "./"`` points at the plugin root, which is a legal
        # place to keep a skill. A file-valued field naming the root is
        # meaningless, so only directory-valued fields accept it.
        if candidate == root and not want_dir:
            continue
        if safe_is_dir(candidate) if want_dir else safe_is_file(candidate):
            found.append(candidate)
    return found


def codex_declared_hook_files(plugin_dir: Path) -> List[Path]:
    """Hook files a Codex plugin manifest declares through ``hooks``."""
    return codex_declared_paths(plugin_dir, "hooks", want_dir=False)


def codex_declared_skill_dirs(plugin_dir: Path) -> List[Path]:
    """Skill directories a Codex plugin manifest declares through ``skills``.

    The field does not have to say ``./skills`` — a plugin may bundle them
    under ``./bundled-skills`` instead. Scanning only the literal
    ``skills/`` directory misses those, and for a plugin installed under
    the hidden ``.codex/plugins/`` tree nothing else walks them, so their
    SKILL.md files would reach no rule at all.
    """
    return codex_declared_paths(plugin_dir, "skills", want_dir=True)


def codex_declared_mcp_files(plugin_dir: Path) -> List[Path]:
    """MCP config files a Codex plugin manifest declares through ``mcpServers``.

    Only ``.mcp.json`` is conventional, and it is attached on sight. A
    manifest may point the field at a different file, and those servers are
    the same surface — a command the host will spawn — so they reach
    mcp-valid-json and mcp-prohibited the same way.
    """
    return codex_declared_paths(plugin_dir, "mcpServers", want_dir=False)


def codex_inline_hooks(plugin_dir: Path) -> List[Dict[str, Any]]:
    """Hooks a Codex plugin manifest declares inline, in hooks.json shape.

    :func:`codex_declared_hook_files` covers the path forms; this covers
    the object forms, which carry exactly the same executable commands —
    without it a ``curl | sh`` SessionStart hook written inline is
    invisible to hooks-dangerous and hooks-prohibited.

    One document per declared object, never a merge (see
    :func:`inline_documents`): separate blocks let every occurrence be
    judged.

    Both ``{"hooks": {...}}`` (mirroring a hooks.json document) and a bare
    event map are accepted.
    """
    return inline_documents(codex_manifest(plugin_dir).get("hooks"), "hooks")


def codex_inline_mcp_servers(plugin_dir: Path) -> List[Dict[str, Any]]:
    """MCP servers a Codex plugin manifest declares inline.

    ``mcpServers`` is documented as a path, but real plugins ship the map
    inline the way Claude Code's loader accepts it. Those servers name
    commands the host will spawn, so they belong in front of the MCP rules
    whether they arrived by path or by value.

    One document per declared object, never a merge (see
    :func:`inline_documents`). Both ``{"mcpServers": {...}}`` and a bare
    server map are accepted, matching what ``McpBlock.servers`` reads.
    """
    return inline_documents(codex_manifest(plugin_dir).get("mcpServers"), "mcpServers")


def codex_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries a Codex manifest of its own.

    The authorship evidence the Claude rules stand down on, asked directly
    of the filesystem rather than of discovery — discovery is switched off
    by a ``--type`` override, and the answer must be override-invariant.

    Containment is checked the way discovery checks it: a ``.codex-plugin``
    or a ``plugin.json`` symlinked out of the plugin is not this plugin's
    manifest, and exempting on it would leave the directory covered by no
    rule at all.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return False
    manifest_dir = plugin_dir / CODEX_PLUGIN_MANIFEST[0]
    if contained_resolve(manifest_dir, root) is None:
        return False
    manifest = plugin_dir.joinpath(*CODEX_PLUGIN_MANIFEST)
    if contained_resolve(manifest, root) is None:
        return False
    return safe_is_file(manifest)


def codex_marker_escapes(plugin_dir: Path) -> bool:
    """Whether *plugin_dir*'s ``.codex-plugin`` marker points out of the plugin.

    The containment half of :func:`codex_manifest_is_contained`, asked
    without requiring the manifest to exist: a directory carrying no marker
    at all does not escape, so a claim over it still stands and
    ``codex-plugin-json-valid`` still reports the missing manifest. A marker
    (or a ``plugin.json`` inside it) that resolves elsewhere is another
    plugin's — or another tree's — and no claim may adopt it.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        # Containment cannot be proven, so fail closed.
        return True
    manifest_dir = plugin_dir / CODEX_PLUGIN_MANIFEST[0]
    if not (safe_exists(manifest_dir) or safe_is_symlink(manifest_dir)):
        return False
    if contained_resolve(manifest_dir, root) is None:
        return True
    manifest = plugin_dir.joinpath(*CODEX_PLUGIN_MANIFEST)
    return safe_exists(manifest) and contained_resolve(manifest, root) is None
