"""State-free discovery of Antigravity plugins.

Antigravity plugins are the direct children of ``plugins/`` under a
customization root, each declaring itself with a ``plugin.json``. Measured
against ``agy`` 1.1.25: a nested ``plugins/outer/inner/plugin.json`` is not
a plugin, a directory named by a sibling catalog but carrying no manifest
is not a plugin, and a manifest whose ``$schema`` is the Agent Plugins one
*is* claimed — so a directory can belong to both ecosystems at once, and
provenance carries both claims.

**One deliberate divergence.** ``agy`` follows a ``plugin.json`` symlinked
outside the workspace, and a plugin *directory* symlinked outside it, and
loads what it finds. skillsaw does not: reading a file outside the
repository it was pointed at is what T6 asserts it never does, and the cost
is that a plugin assembled by symlink out of the checkout is not linted.
See THREAT_MODEL.md, T6.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set

from skillsaw.formats.antigravity import (
    AGENTS_DIR_NAME,
    ANTIGRAVITY_CONFIG_DIR_NAMES,
    HOOKS_FILENAME,
    MCP_CONFIG_FILENAME,
    PLUGIN_MANIFEST,
    PLUGINS_DIR_NAME,
    REGISTRY_FILENAMES,
    RULES_DIR_NAME,
)
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.utils import read_json_strict


def is_antigravity_plugin_location(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* sits where Antigravity installs a plugin.

    ``<customization root>/plugins/<name>`` and nothing else. Asked of the
    path rather than of the filesystem, because the answer is what keeps a
    root ``plugin.json`` — the Agent Plugins marker — from reading as an
    Antigravity declaration.
    """
    parent = plugin_dir.parent
    return parent.name == PLUGINS_DIR_NAME and parent.parent.name in ANTIGRAVITY_CONFIG_DIR_NAMES


def customization_root_declares_a_file(base: Path, *, is_excluded: Callable[[Path], bool]) -> bool:
    """Whether *base* holds a file only Antigravity reads.

    Its hooks file, its MCP file, one of its registries, or a ``plugins/``
    holding a plugin. ``plugins/`` is asked for a manifest rather than for
    any entry at all, because a Codex catalog is a
    ``plugins/marketplace.json`` and a bare file there is no evidence of
    this host.

    Deliberately not ``rules/`` or ``agents/``: those are the prose the
    tree attaches from a root, so a gate that admitted them would answer
    its own question.

    This is the predicate three of the four roots use. The tree builder
    reads it for ``_agents/`` and ``_agent/`` before attaching their prose,
    and detection reads it for those two *and* for the shared ``.agents/``.
    Only ``.agent/`` — a name no other tool reads — takes the wider
    :func:`customization_root_is_marked`.
    """
    for name in (HOOKS_FILENAME, MCP_CONFIG_FILENAME, *REGISTRY_FILENAMES):
        path = base / name
        if not is_excluded(path) and safe_is_file(path):
            return True
    # Contained against the customization root itself, before the listing:
    # a ``plugins`` symlinked out of that root declares nothing about this
    # host either way, and enumerating it would read a directory outside
    # the root on the strength of its name alone. There is no repository
    # root here — detection and the tree builder both apply that one
    # already — so the root at hand is the boundary.
    resolved_base = safe_resolve(base)
    if resolved_base is None:
        return False
    plugins_dir = base / PLUGINS_DIR_NAME
    if (
        is_excluded(plugins_dir)
        or contained_resolve(plugins_dir, resolved_base) is None
        or not safe_is_dir(plugins_dir)
    ):
        return False
    try:
        children = list(plugins_dir.iterdir())
    except OSError:
        return False
    for child in children:
        manifest = child / PLUGIN_MANIFEST
        if not is_excluded(manifest) and safe_is_file(manifest):
            return True
    return False


def customization_root_is_marked(base: Path, *, is_excluded: Callable[[Path], bool]) -> bool:
    """Whether *base* holds anything only Antigravity reads.

    The root's *presence* is not evidence: ``skills/`` is the shared Agent
    Skills convention every ecosystem reads and ``memory/`` is committed
    project memory that predates Antigravity, so neither says which tool
    the repository configures. Both are left out for exactly that reason.
    What remains is :func:`customization_root_declares_a_file`, plus a
    populated ``rules/`` or ``agents/``.

    Read by ``tool_types`` for ``.agent/`` alone. That root is the
    documented Windsurf-lineage back-compat path and nothing else reads it,
    so its prose is evidence; under the other three a populated ``rules/``
    is not, and they take the narrower predicate.
    """
    if customization_root_declares_a_file(base, is_excluded=is_excluded):
        return True
    for name in (RULES_DIR_NAME, AGENTS_DIR_NAME):
        directory = base / name
        if is_excluded(directory) or not safe_is_dir(directory):
            continue
        try:
            if any(True for _ in directory.iterdir()):
                return True
        except OSError:
            continue
    return False


def antigravity_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries an Antigravity manifest of its own.

    The authorship evidence, asked directly of the filesystem rather than
    of discovery — discovery is switched off by a ``--type`` override, and
    the answer must be override-invariant.

    Existence, not parseability: a manifest that does not parse means
    ``agy`` skips the directory, and reporting that is
    ``antigravity-plugin-json-valid``'s job, which needs the node to exist.

    Containment here is against *plugin_dir*, so a ``plugin.json``
    symlinked out of the plugin is not this plugin's manifest. That is
    narrower than repository containment and does not replace it:
    **every caller must have contained plugin_dir in the repository
    first**, which ``discover_antigravity_plugins`` and
    ``registry_plugin_roots`` both do before calling in.
    """
    if not is_antigravity_plugin_location(plugin_dir):
        return False
    root = safe_resolve(plugin_dir)
    if root is None:
        return False
    manifest = plugin_dir / PLUGIN_MANIFEST
    resolved_manifest = contained_resolve(manifest, root)
    if resolved_manifest is None:
        return False
    return safe_is_file(resolved_manifest)


def antigravity_marker_escapes(plugin_dir: Path) -> bool:
    """Whether *plugin_dir*'s ``plugin.json`` points out of the plugin.

    The containment half of :func:`antigravity_manifest_is_contained`,
    asked without requiring the manifest to exist, so a claim over a
    manifest-less directory still stands.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        # Containment cannot be proven, so fail closed.
        return True
    manifest = plugin_dir / PLUGIN_MANIFEST
    if not (safe_exists(manifest) or safe_is_symlink(manifest)):
        return False
    return contained_resolve(manifest, root) is None


def discover_antigravity_plugins(
    root: Path,
    customization_dirs: List[Path],
    *,
    forced: bool = False,
) -> List[Path]:
    """Return every directory declaring an Antigravity plugin.

    *customization_dirs* are the customization roots the shared walk found,
    so a monorepo package's own ``.agents/`` contributes its plugins the
    way the repository root's does — ``agy`` walks up from the entry
    directory and unions every root on the way.

    *forced* is ``--type antigravity-plugin``: it takes every direct child
    of a ``plugins/`` directory, manifest or not, so the manifest rule has
    a node to report against. It seeds no repository root, unlike the Codex
    and Grok arms: an Antigravity plugin is never the repository root, so a
    seed there would build a node over a directory ``agy`` cannot install.
    """
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    plugins: List[Path] = []
    seen: Set[Path] = set()

    for customization_dir in customization_dirs:
        plugins_dir = customization_dir / PLUGINS_DIR_NAME
        # Containment before the listing, not only before the manifest
        # read: a ``plugins`` symlinked out of the checkout would otherwise
        # have its entries enumerated — names read from outside the
        # repository, and an unbounded directory walked on the strength of
        # a symlink the repository controls.
        if contained_resolve(plugins_dir, resolved_root) is None or not safe_is_dir(plugins_dir):
            continue
        try:
            children = sorted(plugins_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not safe_is_dir(child):
                continue
            # Repository containment first, before the manifest is read:
            # a plugin directory symlinked out of the checkout must not
            # have a file opened inside it at all.
            if contained_resolve(child, resolved_root) is None:
                continue
            if not (forced or antigravity_manifest_is_contained(child)):
                continue
            resolved = safe_resolve(child)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            plugins.append(child)

    return sorted(plugins)


#: How deep an ``inherits`` chain is followed. A registry may name another
#: registry file, which may name a third; the cap bounds a chain that a
#: cycle guard alone would not (a long linear chain of distinct files).
_MAX_INHERITS_DEPTH = 8


def _registry_entry_path(root: Path, value: object) -> Optional[Path]:
    """One registry ``path`` as a repository path, or ``None``.

    Measured: ``tools/shared/plugins``, ``./tools/shared/plugins`` and an
    absolute path inside the workspace all resolve to the same directory.
    ``~/``-relative is documented and is deliberately not followed — it
    names a location outside the repository, which is the one thing T6 says
    skillsaw never reads.
    """
    if not isinstance(value, str) or not value or value.startswith("~"):
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return contained_resolve(candidate, root)
    return contained_resolve(root / candidate, root)


def resolve_registry_entries(
    root: Path,
    customization_dirs: Iterable[Path],
    filename: str,
    *,
    is_excluded: Callable[[Path], bool],
) -> List[Path]:
    """Directories a registry names, resolved and contained in *root*.

    A ``customizations.JSONConfig`` registry — ``plugins.json``,
    ``agents.json`` — points ``agy`` at customization living outside the
    customization root. Measured against ``agy`` 1.1.25: a ``plugins.json``
    naming ``tools/shared/plugins`` loads every plugin under it, and an
    ``agents.json`` naming a directory loads the agents in it, so the
    content really is part of the repository's configuration and belongs in
    the lint tree.

    ``inherits`` names another *registry file* whose entries are read as
    well; a directory there loads nothing, and is skipped. Followed
    recursively with a cycle guard and a depth cap.

    ``include_only`` and ``exclude`` are read by ``agy`` and deliberately
    ignored here, on the same policy as a hook-level ``"enabled": false``:
    skillsaw reports what a repository ships, not what it currently loads,
    and a filter is a one-line commit away from loading the rest.

    Escapes are dropped rather than reported — the registry rule owns
    whether an entry is well-formed, and a path leaving the repository is
    the one thing no reader here may follow.
    """
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    found: List[Path] = []
    seen: Set[Path] = set()
    visited_registries: Set[Path] = set()

    def read_registry(path: Path, depth: int) -> None:
        resolved = contained_resolve(path, resolved_root)
        if resolved is None or resolved in visited_registries or is_excluded(path):
            return
        visited_registries.add(resolved)
        if not safe_is_file(resolved):
            return
        # The reader the block uses: strict about the tokens ``agy``
        # refuses, lenient about a repeated key it collapses.
        data, error = read_json_strict(resolved, allow_duplicate_keys=True)
        if error or not isinstance(data, dict):
            return
        entries = data.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                directory = _registry_entry_path(resolved_root, entry.get("path"))
                if directory is None or is_excluded(directory) or not safe_is_dir(directory):
                    continue
                if directory not in seen:
                    seen.add(directory)
                    found.append(directory)
        if depth >= _MAX_INHERITS_DEPTH:
            return
        inherits = data.get("inherits")
        if not isinstance(inherits, list):
            return
        for entry in inherits:
            if not isinstance(entry, dict):
                continue
            target = _registry_entry_path(resolved_root, entry.get("path"))
            # Measured: a directory in ``inherits`` loads nothing. Only a
            # registry *file* is followed.
            if target is not None:
                read_registry(target, depth + 1)

    for customization_dir in customization_dirs:
        read_registry(customization_dir / filename, 0)
    return sorted(found)


def registry_plugin_roots(root: Path, directories: Iterable[Path]) -> List[Path]:
    """Plugin roots among the directories a ``plugins.json`` names.

    Measured: a named directory carrying its own ``plugin.json`` is that
    one plugin; a named directory holding several is the container, and
    each child carrying a manifest loads. Both spellings appear in the
    wild, and ``agy`` accepts either.

    Containment first, per candidate, before any manifest is read — the
    same order :func:`discover_antigravity_plugins` uses. The entry paths
    arrive contained, but the container expansion below reads the
    filesystem, and a symlinked child of a contained directory points
    wherever it likes: without this a ``plugins.json`` naming an ordinary
    directory would have skillsaw open, claim and node-ify a ``plugin.json``
    outside the repository.
    """
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []
    roots: List[Path] = []
    seen: Set[Path] = set()
    for directory in directories:
        candidates = [directory]
        if not safe_is_file(directory / PLUGIN_MANIFEST):
            try:
                candidates = sorted(child for child in directory.iterdir() if safe_is_dir(child))
            except OSError:
                continue
        for candidate in candidates:
            resolved = contained_resolve(candidate, resolved_root)
            if resolved is None or resolved in seen:
                continue
            if not safe_is_file(candidate / PLUGIN_MANIFEST):
                continue
            if antigravity_marker_escapes(candidate):
                continue
            seen.add(resolved)
            roots.append(resolved)
    return roots
