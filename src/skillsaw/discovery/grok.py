"""Grok Build discovery: what Grok plugin content exists on disk, and where.

State-free enumeration of Grok plugin directories, catalog files, and the
local plugin directories a catalog or project configuration declares. Every
function takes explicit arguments — a repository root, the ``.grok-plugin`` directories the shared
walk found, an exclusion callback — and returns data; caching, ``--type``
gating, and the provenance verdicts over this evidence stay on
``RepositoryContext`` (see "Ecosystem provenance" in the development rules).

There is no install-root helper here, and that is deliberate. Codex has one
because ``.codex/plugins/`` holds plugins a developer added to their own
checkout, which autofix must not rewrite. Grok's repository-resident plugin
location is ``.grok/plugins/``, which the user guide calls "Project, shared
through version control" — authored content the repository owns. Its
auto-trusted counterpart, ``~/.grok/plugins/``, lives under the user's home
and never appears in a lint. So nothing here is vendor-managed, and
``Linter._is_vendor_managed`` needs no Grok arm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Set

from skillsaw.formats.grok import (
    MARKETPLACE_FILENAME,
    PLUGIN_CONFIG_LIST_FIELDS,
    PLUGIN_DIR_NAME,
    PLUGIN_MANIFEST,
    grok_local_source_path,
    grok_marker_escapes,
)
from skillsaw.formats.grok_catalog import read_catalog_json
from skillsaw.discovery.excludes import is_root_or_ancestor_excluded
from skillsaw.utils import read_toml
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)

# Grok reads a marketplace catalog from ``<root>/.grok-plugin/marketplace.json``
# and a plugin manifest from ``<plugin>/.grok-plugin/plugin.json``. Each has a
# fallback chain — ``formats.grok.CATALOG_PATHS`` and ``MANIFEST_PATHS``, whose
# orders differ — and skillsaw claims only the ``.grok-plugin``
# spelling of either: a directory whose one declaration is Claude's is a Claude
# plugin, and claiming it for Grok as well would put every Claude plugin in the
# repository under two ecosystems' format rules.
GROK_CATALOG = (PLUGIN_DIR_NAME, MARKETPLACE_FILENAME)
GROK_PLUGIN_MANIFEST = (PLUGIN_DIR_NAME, PLUGIN_MANIFEST)


def _read_json_or_none(path: Path) -> Any:
    """Read catalog declarations for diagnostic ownership.

    The host reader distinguishes accepted source/unknown duplicates from
    syntax failures. Typed metadata errors belong to the validity rule:
    they must not reclassify otherwise declared Grok content as Claude.
    """
    data, error = read_catalog_json(path)
    return None if error else data


def grok_marketplace_path(root_path: Path) -> Path:
    """Path the repository-root Grok catalog would live at."""
    return root_path.joinpath(*GROK_CATALOG)


def enumerate_grok_catalogs(
    root_path: Path,
    containment_root: Path,
    marker_dirs: Iterable[Path],
    is_excluded: Callable[[Path], bool],
    *,
    seed_forced_primary: bool = False,
) -> List[Path]:
    """The one enumeration of Grok catalog files.

    ``marketplace.json`` inside any ``.grok-plugin`` directory — the
    repository root's, or a monorepo package's, which the shared walk hands
    over as *marker_dirs*. Taken on existence alone, so broken JSON still
    reaches the catalog rule instead of hiding the very defect it reports.
    The filename is reserved, so nothing here duck-types a sibling.

    Stateless by design: the ``--type`` gate and the per-context cache live
    on ``RepositoryContext``. The discovery-gated caller passes
    ``seed_forced_primary`` so a forced marketplace type still seeds the
    root entrypoint; the declaration-side (provenance) caller does not.
    *containment_root* is the resolved root catalogs must stay inside;
    *is_excluded* applies the context's exclude patterns.
    """

    def _keep(path: Path) -> bool:
        # Two boundaries, for two different reasons. The checkout, because a
        # catalog resolving outside it is not this repository's to read. And
        # its own marketplace root, the same per-package boundary
        # ``discover_grok_plugins._add`` enforces for a manifest:
        # ``pkg-a/.grok-plugin -> ../pkg-b/.grok-plugin`` stays in the
        # checkout, and keeping it would file pkg-b's catalog findings at
        # pkg-a's path and deduplicate pkg-b's own candidate away.
        # Exclusions are applied here rather than at each reader, so an
        # excluded catalog claims nothing either.
        if contained_resolve(path, containment_root) is None or is_excluded(path):
            return False
        marketplace_root = safe_resolve(path.parent.parent)
        return (
            marketplace_root is not None and contained_resolve(path, marketplace_root) is not None
        )

    found: List[Path] = []
    seen: Set[Path] = set()
    primary = grok_marketplace_path(root_path)
    candidates = [primary, *(directory / MARKETPLACE_FILENAME for directory in marker_dirs)]
    for candidate in candidates:
        # Existence or a (possibly dangling) symlink, not is_file(): a
        # directory or dangling link at the reserved entrypoint is an
        # unusable catalog, and dropping it would declassify the repository
        # instead of letting the catalog rule report it.
        if not (safe_exists(candidate) or safe_is_symlink(candidate)):
            continue
        if not _keep(candidate):
            continue
        # Resolved comparison: the walk reports the root's own marker
        # directory too, and on a case-insensitive filesystem
        # ``MARKETPLACE.JSON`` is the same file under another spelling.
        resolved = safe_resolve(candidate) or candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(candidate)

    if not found and seed_forced_primary and _keep(primary):
        # ``_keep`` also enforces containment, so a forced type cannot seed
        # a path outside the checkout through a symlinked catalog.
        found.append(primary)
    return found


def grok_local_sources(catalog_files: Iterable[Path]) -> List[Path]:
    """Local plugin directories declared by a Grok catalog.

    Each catalog resolves and contains its ``source`` paths against its own
    marketplace root — the directory holding ``.grok-plugin/`` — so a package
    that is a marketplace of its own resolves against the package, not the
    checkout. Sources that escape the marketplace root are dropped here,
    which is the boundary Grok enforces and the catalog rule reports: a
    wider one would claim a sibling package for Grok and take it out of
    every other ecosystem's format scope.

    An entry without a string ``name`` declares nothing either: Grok drops it,
    so claiming its target would switch an otherwise unmarked plugin's
    Claude-scoped rules off and attach Grok configuration for content Grok
    never installs.
    """
    resolved: List[Path] = []
    for catalog in catalog_files:
        marketplace_root = safe_resolve(catalog.parent.parent)
        if marketplace_root is None:
            continue
        data = _read_json_or_none(catalog)
        if not isinstance(data, dict):
            continue
        entries = data.get("plugins", [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            path = grok_local_source_path(entry.get("source"))
            if path is None:
                continue
            candidate = contained_resolve(marketplace_root / path, marketplace_root)
            if candidate is None:
                continue  # the catalog rule reports the unresolvable path
            resolved.append(candidate)
    return resolved


def grok_config_sources(
    root_path: Path,
    tool_dirs: Iterable[Path],
    is_excluded: Callable[[Path], bool],
) -> List[Path]:
    """Contained plugin paths declared by each authored ``.grok/config.toml``.

    Grok 1.0.13 turns these strings directly into PathBufs, relative to the
    session cwd. Static lint assumes a session launched beside each declaring
    ``.grok/`` directory; it never uses skillsaw's process cwd. Absolute paths
    must still stay in the checkout. Environment and home expansion are not
    inferred from the machine running the linter.

    Project paths join the live config only after folder trust; plugin
    component trust is separate. These are declaration claims, not promises
    of trust or enablement. A path names one plugin, not a bundle to recurse.
    """
    root = safe_resolve(root_path)
    if root is None:
        return []
    found: Set[Path] = set()
    for directory in tool_dirs:
        config = directory / "config.toml"
        if (
            contained_resolve(config, root) is None
            or is_root_or_ancestor_excluded(config, root, is_excluded)
            or not safe_is_file(config)
        ):
            continue
        data, error = read_toml(config)
        plugins = data.get("plugins") if isinstance(data, dict) and not error else None
        if not isinstance(plugins, dict):
            continue
        # The released typed table rejects an invalid sibling list too.
        if any(
            not isinstance(value := plugins.get(field, []), list)
            or any(not isinstance(item, str) for item in value)
            for field in PLUGIN_CONFIG_LIST_FIELDS
        ):
            continue
        for value in plugins.get("paths", []):
            # Rust's empty PathBuf fails is_dir(); Path('') would mean '.'.
            if not value:
                continue
            candidate = contained_resolve(directory.parent / value, root)
            if (
                candidate is not None
                and safe_is_dir(candidate)
                and not grok_marker_escapes(candidate)
                and not is_root_or_ancestor_excluded(candidate, root, is_excluded)
            ):
                found.add(candidate)
    return sorted(found)


def discover_grok_plugins(
    root_path: Path,
    marker_dirs: Iterable[Path],
    local_sources: Iterable[Path],
    *,
    forced: bool = False,
) -> List[Path]:
    """Directories declaring a Grok plugin.

    The reserved ``.grok-plugin/`` directory carrying a ``plugin.json`` is
    the evidence, wherever in the tree it sits — the shared walk hands over
    every one as *marker_dirs* — plus *local_sources*, the contained paths
    declared by catalogs and project configuration. *forced* seeds the
    repository root when a ``--type`` override demands the plugin type with
    no marker present. Only the :data:`GROK_PLUGIN_MANIFEST` spelling counts,
    for the reason recorded there.
    """
    found: List[Path] = []
    seen: Set[Path] = set()
    root = safe_resolve(root_path) or root_path

    def _contained(path: Path) -> Optional[Path]:
        resolved = safe_resolve(path)
        if resolved is None:
            return None
        # ``is_relative_to`` is True on equality, so the root itself passes.
        return resolved if resolved.is_relative_to(root) else None

    def _add(directory: Path, *, require_manifest: bool) -> None:
        # Either half can be the symlink out of the repository: the plugin
        # directory itself, or its ``.grok-plugin`` under a real directory.
        # Both would make skillsaw read an out-of-tree manifest.
        resolved = _contained(directory)
        if resolved is None or resolved in seen:
            return
        marker = directory / PLUGIN_DIR_NAME
        has_marker = safe_exists(marker) or safe_is_symlink(marker)
        if require_manifest and not has_marker:
            return
        if has_marker:
            # The marker must resolve within *this plugin*, not merely the
            # repository: ``plugins/a/.grok-plugin -> plugins/b/.grok-plugin``
            # stays in the checkout, and a repo-wide check would let plugin
            # A be discovered using B's manifest.
            if contained_resolve(marker, resolved) is None:
                return
            manifest = marker / PLUGIN_MANIFEST
            if safe_exists(manifest) and contained_resolve(manifest, resolved) is None:
                return
            if require_manifest and not safe_exists(manifest):
                # A catalog claim over a manifest-less directory still
                # stands; a bare marker directory on its own does not
                # declare a plugin.
                return
        seen.add(resolved)
        found.append(directory)

    for marker in marker_dirs:
        if safe_is_dir(marker):
            _add(marker.parent, require_manifest=True)

    for source in local_sources:
        _add(source, require_manifest=False)

    if not found and forced:
        # One predicate: a marker that escapes the plugin, or a root that
        # will not resolve, is what blocks the seed — unconditional seeding
        # would hand a rejected marker straight back past the containment
        # gate. A *contained* marker with no manifest beside it does not
        # block it: that directory is exactly what ``--type grok-plugin``
        # was asked about, and its conventional components are what Grok
        # installs it from.
        if _contained(root_path) and not grok_marker_escapes(root_path):
            found.append(root_path)

    return found
