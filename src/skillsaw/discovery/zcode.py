"""ZCode discovery: what ZCode plugin content exists on disk, and where.

State-free enumeration of ZCode plugin directories, the marketplace catalog,
and the local plugin directories the catalog lists. Every function takes
explicit arguments and returns data; caching, the ``--type`` gate and the
provenance verdicts stay on ``RepositoryContext`` (see "Ecosystem
provenance" in the development rules).

There is no install-root or config-path helper here. ZCode installs plugins
under the user's ``~/.zcode``, which never appears in a lint, and a
project's ``.zcode/config.json`` cannot add plugin directories: the loader
strips ``plugins.dirs`` from project configuration
(``adapters/src/config/project-config.adapter.ts:132-136`` in
``zai-org/ZCode``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set

from skillsaw.formats.zcode import (
    CLAUDE_CATALOG,
    MARKETPLACE_FILENAME,
    PLUGIN_DIR_NAME,
    PLUGIN_MANIFEST,
    catalog_entries,
    catalog_plugin_base,
    entry_local_source,
    zcode_marker_escapes,
)
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.utils import read_json


def zcode_marketplace_path(root_path: Path) -> Path:
    """Path the repository-root ZCode catalog would live at."""
    return root_path / MARKETPLACE_FILENAME


def enumerate_zcode_catalogs(
    root_path: Path,
    containment_root: Path,
    has_plugin_markers: bool,
    is_excluded: Callable[[Path], bool],
    *,
    seed_forced_primary: bool = False,
) -> List[Path]:
    """The repository's ZCode catalog, as a zero- or one-element list.

    ZCode reads ``.claude-plugin/marketplace.json`` and falls back to the
    root ``marketplace.json``. Only the fallback is ZCode's to claim — the
    first is Claude's file, which the Claude marketplace rules own — and
    only in a repository carrying a ``.zcode-plugin`` marker: a bare
    ``marketplace.json`` is a generic filename no ecosystem reserves.
    *seed_forced_primary* drops the marker requirement and seeds the path
    even when the file is absent, so a forced ``--type zcode-marketplace``
    reports a missing catalog instead of a clean run.

    Existence, not parseability: broken JSON must still reach the catalog
    rule rather than hide the very defect it reports.
    """
    primary = zcode_marketplace_path(root_path)
    if not (has_plugin_markers or seed_forced_primary):
        return []
    if safe_exists(root_path.joinpath(*CLAUDE_CATALOG)):
        return []
    if not (safe_exists(primary) or safe_is_symlink(primary)) and not seed_forced_primary:
        return []
    if contained_resolve(primary, containment_root) is None or is_excluded(primary):
        return []
    return [primary]


def zcode_local_sources(catalog_files: Iterable[Path]) -> List[Path]:
    """Resolved checkout directories a ZCode catalog lists as local sources.

    Each source resolves against the catalog's plugin base and must stay
    inside its marketplace root; a source that escapes is dropped here and
    reported by the catalog rule. An entry without a usable ``name`` is
    dropped by ZCode itself, so it claims nothing.
    """
    resolved: List[Path] = []
    for catalog in catalog_files:
        marketplace_root = safe_resolve(catalog.parent)
        if marketplace_root is None or not safe_is_file(catalog):
            continue  # a FIFO or device would block the read
        data, error = read_json(catalog)
        if error or not isinstance(data, dict):
            continue
        base = catalog_plugin_base(catalog.parent, data)
        for entry in catalog_entries(data):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            path = entry_local_source(entry, base)
            if path is None:
                continue
            candidate = contained_resolve(path, marketplace_root)
            if candidate is not None:
                resolved.append(candidate)
    return resolved


def discover_zcode_plugins(
    root_path: Path,
    marker_dirs: Iterable[Path],
    local_sources: Iterable[Path],
    *,
    forced: bool = False,
) -> List[Path]:
    """Directories declaring a ZCode plugin.

    A ``.zcode-plugin/`` directory holding a ``plugin.json``, wherever the
    shared walk found it (*marker_dirs*), plus the catalog's
    *local_sources*. *forced* seeds the repository root when ``--type
    zcode-plugin`` asks for a plugin and no marker is present.
    """
    found: List[Path] = []
    seen: Set[Path] = set()
    root = safe_resolve(root_path) or root_path

    def _add(directory: Path, *, require_manifest: bool) -> None:
        resolved: Optional[Path] = safe_resolve(directory)
        if resolved is None or not resolved.is_relative_to(root) or resolved in seen:
            return
        if zcode_marker_escapes(directory):
            return
        if require_manifest and not safe_exists(marker_dir_manifest(directory)):
            return
        seen.add(resolved)
        found.append(directory)

    for marker in marker_dirs:
        if safe_is_dir(marker):
            _add(marker.parent, require_manifest=True)
    for source in local_sources:
        if safe_is_dir(source):
            _add(source, require_manifest=False)
    if not found and forced and not zcode_marker_escapes(root_path):
        found.append(root_path)
    return found


def marker_dir_manifest(plugin_dir: Path) -> Path:
    """Where *plugin_dir*'s ``.zcode-plugin/plugin.json`` would be."""
    return plugin_dir / PLUGIN_DIR_NAME / PLUGIN_MANIFEST
