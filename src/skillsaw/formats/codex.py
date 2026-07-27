"""OpenAI Codex plugin-format helpers.

Functions over Codex manifest and marketplace values that need no
repository state — only a plugin directory. ``context`` uses them while
building the lint tree; rules and the docs extractor import them directly.

Kept out of ``context.py`` deliberately. Held as methods there they were
feature envy against a ``plugin_dir``, and every rule that wanted one had
to reach through ``RepositoryContext`` to get it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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


def safe_resolve(path: Path) -> Optional[Path]:
    """``path.resolve()``, or ``None`` when the path cannot be resolved.

    Discovery runs while ``RepositoryContext`` is being constructed, before
    any rule can report anything, and it resolves strings taken straight
    out of a manifest. ``Path.resolve()`` raises ``ValueError`` on an
    embedded NUL, ``OSError`` on an unreadable parent, and — on a symlink
    loop — ``RuntimeError`` before Python 3.13 but ``OSError`` from 3.13
    on. This project supports 3.9 through 3.14, so all three have to be
    caught; any of them would abort the whole lint instead of producing
    the violation the manifest deserves. Returning ``None`` drops the
    candidate from discovery and leaves the reporting to the rules.
    """
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def _safe_stat(path: Path, predicate: str) -> bool:
    """``path.<predicate>()``, or ``False`` when the path cannot be stat'd.

    ``safe_resolve`` is not enough on its own: ``Path.resolve()`` does not
    stat, so it happily returns a path that the very next ``is_dir()``
    raises on. ``pathlib`` swallows only ``ENOENT``/``ENOTDIR``/``EBADF``/
    ``ELOOP`` on Python 3.9 through 3.12, so a manifest declaring a
    4000-character path raises ``ENAMETOOLONG`` there — from inside
    ``RepositoryContext.__init__``, where the ``rule-execution-error``
    guard cannot reach it. The whole lint aborts with a traceback and
    reports nothing at all, on a repository whose only defect is one
    over-long string in a JSON file.
    """
    try:
        return bool(getattr(path, predicate)())
    except (OSError, ValueError):
        return False


def safe_is_dir(path: Path) -> bool:
    """``path.is_dir()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_dir")


def safe_is_file(path: Path) -> bool:
    """``path.is_file()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_file")


def safe_exists(path: Path) -> bool:
    """``path.exists()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "exists")


def safe_is_symlink(path: Path) -> bool:
    """``path.is_symlink()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_symlink")


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

    Goes through the shared cached reader so a UTF-8 BOM is stripped and
    repeated reads cost nothing — discovery, the validity rule and the
    registration rule all read these files.
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
        candidate = safe_resolve(plugin_dir / item)
        if candidate is None or not candidate.is_relative_to(root):
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
    the object forms, which carry exactly the same executable commands and
    so belong in front of the same hook rules. Without it a ``curl | sh``
    SessionStart hook written inline is invisible to hooks-dangerous and
    hooks-prohibited.

    One document per declared object, never a merge. Merging looked tidier
    but silently dropped occurrences: an array that repeats an event has to
    lose one of the two values, and whichever rule loses is a defect
    nothing else reports — ``codex-plugin-json-valid`` deliberately skips
    hook objects, so a malformed ``SessionStart`` overwritten by a later
    valid one goes unreported, and a valid one overwritten by a malformed
    one loses its commands to hooks-dangerous. Separate blocks let every
    occurrence be judged.

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

    One document per declared object, for the reason spelled out in
    :func:`codex_inline_hooks`: merging by server name would drop a second
    ``same`` entry missing its ``command``, hiding exactly the structural
    error mcp-valid-json exists to report.

    Both ``{"mcpServers": {...}}`` and a bare server map are accepted,
    matching what ``McpBlock.servers`` already reads.
    """
    return inline_documents(codex_manifest(plugin_dir).get("mcpServers"), "mcpServers")


def codex_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries a Codex manifest of its own.

    The authorship evidence the Claude rules stand down on, asked directly
    of the filesystem rather than of discovery. Discovery is switched off
    by an explicit ``--type`` override; reading the exemption from it would
    make ``skillsaw lint --type marketplace`` restore exactly the false
    positives this exemption removes — the same repository would get two
    different answers from two invocations.

    Containment is checked the way discovery checks it: a ``.codex-plugin``
    or a ``plugin.json`` symlinked out of the plugin is not this plugin's
    manifest, and exempting on it would leave the directory covered by no
    rule at all.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return False
    manifest_dir = plugin_dir / CODEX_PLUGIN_MANIFEST[0]
    resolved_dir = safe_resolve(manifest_dir)
    if resolved_dir is None or not resolved_dir.is_relative_to(root):
        return False
    manifest = plugin_dir.joinpath(*CODEX_PLUGIN_MANIFEST)
    resolved = safe_resolve(manifest)
    if resolved is None or not resolved.is_relative_to(root):
        return False
    return safe_is_file(manifest)
