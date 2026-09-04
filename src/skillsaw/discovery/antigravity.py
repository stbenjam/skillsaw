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
from typing import List, Set

from skillsaw.formats.antigravity import (
    ANTIGRAVITY_CONFIG_DIR_NAMES,
    PLUGIN_MANIFEST,
    PLUGINS_DIR_NAME,
)
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)


def is_antigravity_plugin_location(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* sits where Antigravity installs a plugin.

    ``<customization root>/plugins/<name>`` and nothing else. Asked of the
    path rather than of the filesystem, because the answer is what keeps a
    root ``plugin.json`` — the Agent Plugins marker — from reading as an
    Antigravity declaration.
    """
    parent = plugin_dir.parent
    return parent.name == PLUGINS_DIR_NAME and parent.parent.name in ANTIGRAVITY_CONFIG_DIR_NAMES


def antigravity_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries an Antigravity manifest of its own.

    The authorship evidence, asked directly of the filesystem rather than
    of discovery — discovery is switched off by a ``--type`` override, and
    the answer must be override-invariant.

    Existence, not parseability: a manifest that does not parse means
    ``agy`` skips the directory, and reporting that is
    ``antigravity-plugin-json-valid``'s job, which needs the node to exist.
    Containment is checked the way discovery checks it, so a ``plugin.json``
    symlinked out of the plugin is not this plugin's manifest.
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
        if not safe_is_dir(plugins_dir):
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
