"""OpenAI Codex discovery: what Codex content exists on disk, and where.

State-free enumeration of Codex plugin directories, catalog files, local
catalog sources, and the personal-install location. Every function takes
explicit arguments — a repository root, a containment root, an exclusion
callback — and returns data; caching, ``--type`` gating, and the
provenance verdicts over this evidence stay on ``RepositoryContext``
(see "Ecosystem provenance" in the development rules).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Set

from skillsaw.formats.codex import CODEX_PLUGIN_MANIFEST, codex_local_source_path
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.utils import read_json

# Codex reads a repo marketplace from ``.agents/plugins/marketplace.json``
# and a plugin manifest from ``<plugin>/.codex-plugin/plugin.json``.
# It also accepts ``.claude-plugin/marketplace.json`` for backward
# compatibility, but skillsaw leaves that path to the Claude rules —
# the schemas differ (Codex drops ``owner`` and adds ``policy``,
# ``category`` and ``interface``), so validating one file against both
# would report contradictory violations.
CODEX_MARKETPLACE_DIR = (".agents", "plugins")
CODEX_MARKETPLACE_FILENAME = "marketplace.json"
# Where Codex installs plugins a developer added to their own checkout,
# as opposed to plugins the repository authors.
CODEX_INSTALL_DIR = (".codex", "plugins")


def _is_marketplace_filename(name: str) -> bool:
    """Whether *name* is a Codex catalog by name alone.

    Qualified names (``openai/plugins`` ships ``api_marketplace.json``) must
    end at a separator — a bare ``endswith`` would also claim
    ``notamarketplace.json`` and lint it as a catalog on spelling alone.
    """
    lowered = name.lower()
    if lowered == "marketplace.json":
        return True
    return lowered.endswith("marketplace.json") and lowered[-17] in "-_."


def _looks_like_codex_catalog(data: Any) -> bool:
    """Positive catalog evidence: a ``plugins`` list with a sourced entry.

    The key shape alone also matches version-pin siblings like
    ``plugin-versions.json`` ({name, version} entries, no sources), which
    Codex never reads. One predicate shared by discovery and
    ``codex_catalog_exists`` so the Claude stand-down can never trigger on
    a sibling discovery itself refuses to lint.
    """
    return (
        isinstance(data, dict)
        and isinstance(data.get("plugins"), list)
        and any(isinstance(entry, dict) and "source" in entry for entry in data["plugins"])
    )


def _read_json_or_none(path: Path) -> Any:
    """Parsed JSON at *path*, or ``None`` when absent or unparseable.

    Uses the shared cached reader: strips a UTF-8 BOM, and repeated reads
    of the same manifest cost nothing.
    """
    data, error = read_json(path)
    return None if error else data


def codex_marketplace_path(root_path: Path) -> Path:
    """Path the Codex repo marketplace manifest would live at."""
    return root_path.joinpath(*CODEX_MARKETPLACE_DIR, CODEX_MARKETPLACE_FILENAME)


def enumerate_codex_catalogs(
    root_path: Path,
    containment_root: Path,
    is_excluded: Callable[[Path], bool],
    *,
    seed_forced_primary: bool = False,
) -> List[Path]:
    """The one enumeration of Codex catalog files.

    ``marketplace.json`` and marketplace-named siblings (openai/plugins
    ships ``api_marketplace.json``) are taken on existence alone, so
    broken JSON still reaches codex-marketplace-json-valid instead of
    hiding the very defect it reports. Any other ``*.json`` must
    duck-type as a marketplace — the directory is not reserved, and
    unrelated JSON must not be linted as a catalog. Every catalog
    counts, not just the primary.

    Stateless by design: the ``--type`` gate and the per-context cache
    live on ``RepositoryContext``. The discovery-gated caller passes
    ``seed_forced_primary`` so a forced marketplace type still seeds the
    primary entrypoint; the declaration-side (provenance) caller does
    not, and its result is never cached through the discovery slot.
    *containment_root* is the resolved root catalogs must stay inside;
    *is_excluded* applies the context's exclude patterns.
    """
    root = containment_root

    def _inside(path: Path) -> bool:
        # A catalog resolving outside the checkout is not this
        # repository's to read — and codex-marketplace-registration
        # writes the catalog back, so following a symlink out would
        # overwrite an external file.
        return contained_resolve(path, root) is not None

    def _keep(path: Path) -> bool:
        # Exclusions applied here, not at each reader: ``skillsaw docs``
        # reads this list directly, so an excluded catalog would
        # otherwise still supply published pages and the generated title.
        return _inside(path) and not is_excluded(path)

    found: List[Path] = []
    primary = codex_marketplace_path(root_path)
    # Existence or a (possibly dangling) symlink, not is_file(): a
    # directory or dangling link at the reserved entrypoint is an
    # unusable catalog, and dropping it would declassify the repository
    # instead of letting codex-marketplace-json-valid report it.
    if (safe_exists(primary) or safe_is_symlink(primary)) and _keep(primary):
        found.append(primary)

    primary_resolved = safe_resolve(primary)
    marketplace_dir = root_path.joinpath(*CODEX_MARKETPLACE_DIR)
    if safe_is_dir(marketplace_dir):
        try:
            siblings = sorted(marketplace_dir.glob("*.json"))
        except OSError:
            siblings = []
        for candidate in siblings:
            # Resolved comparison: on a case-insensitive filesystem
            # ``MARKETPLACE.JSON`` is the primary under a different
            # spelling, and path equality would list the file twice.
            candidate_resolved = safe_resolve(candidate)
            if candidate_resolved is not None and candidate_resolved == primary_resolved:
                continue
            if not _keep(candidate):
                continue
            if _is_marketplace_filename(candidate.name):
                found.append(candidate)
                continue
            if _looks_like_codex_catalog(_read_json_or_none(candidate)):
                found.append(candidate)

    if not found and seed_forced_primary and _keep(primary):
        # ``_keep`` also enforces containment: the registration rule
        # writes this file back, so seeding an unchecked path would
        # let ``fix --suggest`` rewrite a file outside the checkout
        # through a symlinked catalog.
        found.append(primary)
    return found


def discover_codex_plugins(
    root_path: Path,
    local_sources: Iterable[Path],
    *,
    forced: bool = False,
) -> List[Path]:
    """Discover directories holding a ``.codex-plugin/plugin.json`` manifest.

    Probes the documented layouts rather than walking the repository —
    the repo root, ``plugins/*``, ``.codex/plugins/*``, and every local
    source declared by the Codex marketplace (*local_sources*, from
    :func:`codex_local_sources`) — keeping discovery O(entries) instead
    of a second whole-repo walk. *forced* seeds the repo root when a
    ``--type`` override demands the plugin type with no marker present.

    The reserved ``.codex-plugin/`` directory is the evidence, not the
    manifest inside it: a directory whose ``plugin.json`` is missing or
    broken is still a Codex plugin, and dropping it here would take the
    ``CODEX_PLUGIN`` type with it and leave the defect unreported
    (``codex-plugin-json-valid`` reports the missing manifest).
    """
    found: List[Path] = []
    seen: Set[Path] = set()

    root = safe_resolve(root_path) or root_path

    def _contained(path: Path) -> Optional[Path]:
        resolved = safe_resolve(path)
        if resolved is None:
            return None
        return resolved if resolved == root or resolved.is_relative_to(root) else None

    def _add(directory: Path) -> None:
        # Either half can be the symlink out of the repository:
        # ``plugins/foo`` itself, or ``plugins/foo/.codex-plugin`` under
        # a real directory. Both would make skillsaw read an out-of-tree
        # manifest, so both are containment-checked.
        resolved = _contained(directory)
        if resolved is None or resolved in seen:
            return
        # The marker must resolve within *this plugin*, not merely the
        # repository: `plugins/a/.codex-plugin -> plugins/b/.codex-plugin`
        # stays in the checkout, and a repo-wide check would let plugin A
        # be discovered and documented using B's manifest.
        #
        # Existence-or-symlink, not ``is_dir()``: a regular file or
        # dangling symlink occupies the reserved name just as surely as
        # a directory, and discarding it would silently un-type the
        # repository; keeping it lets codex-plugin-json-valid report the
        # unreadable manifest.
        manifest_dir = directory / CODEX_PLUGIN_MANIFEST[0]
        if not (safe_exists(manifest_dir) or safe_is_symlink(manifest_dir)):
            return
        if contained_resolve(manifest_dir, resolved) is None:
            return
        # A missing manifest is still a plugin — codex-plugin-json-valid
        # reports it. One that resolves elsewhere is not.
        manifest = directory.joinpath(*CODEX_PLUGIN_MANIFEST)
        manifest_resolved = safe_resolve(manifest)
        if safe_exists(manifest) and (
            manifest_resolved is None or not manifest_resolved.is_relative_to(resolved)
        ):
            return
        seen.add(resolved)
        found.append(directory)

    _add(root_path)

    for parent in (
        root_path / "plugins",
        root_path.joinpath(*CODEX_INSTALL_DIR),
    ):
        if not parent.is_dir():
            continue
        try:
            entries = sorted(parent.iterdir())
        except OSError:
            continue
        for item in entries:
            if item.is_dir() and not item.name.startswith("."):
                _add(item)

    for source in local_sources:
        _add(source)

    if not found and forced:
        # Seed only when the root has no marker at all: discovery
        # rejects a ``.codex-plugin`` that resolves outside the
        # checkout, and unconditional seeding would hand that rejected
        # marker straight back past the containment gate.
        marker = root_path / CODEX_PLUGIN_MANIFEST[0]
        if not (safe_exists(marker) or safe_is_symlink(marker)) and _contained(root_path):
            found.append(root_path)

    return found


def codex_local_sources(root_path: Path, catalog_files: Iterable[Path]) -> List[Path]:
    """Local plugin directories declared by the Codex marketplace.

    Codex resolves ``source.path`` against the *marketplace root* — the
    repository root — not against ``.agents/plugins/``. Sources that
    escape the root are dropped here; ``codex-marketplace-json-valid``
    reports them.
    """
    # Containment compares resolved candidates, so the boundary must be
    # resolved too — a symlinked root passed unresolved would silently
    # drop every local source.
    root_path = safe_resolve(root_path) or root_path
    resolved: List[Path] = []
    for marketplace_file in catalog_files:
        data = _read_json_or_none(marketplace_file)
        if not isinstance(data, dict):
            continue
        entries = data.get("plugins")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = codex_local_source_path(entry.get("source"))
            if path is None:
                continue
            candidate = safe_resolve(root_path / path)
            if candidate is None:
                continue  # codex-marketplace-json-valid reports the path
            if candidate == root_path or candidate.is_relative_to(root_path):
                resolved.append(candidate)
    return resolved


def codex_install_root(root_path: Path) -> Optional[Path]:
    """Resolved ``.codex/plugins/`` install directory, or ``None``."""
    return safe_resolve(root_path.joinpath(*CODEX_INSTALL_DIR))


def is_installed_codex_plugin(
    plugin_dir: Path, root_path: Path, install_root: Optional[Path]
) -> bool:
    """Whether *plugin_dir* sits under the personal-install location.

    *install_root* is the resolved install directory from
    :func:`codex_install_root`; the context resolves it once and passes
    it in.
    """
    if install_root is None:
        return False
    # Lexical first: ``.codex/plugins/foo`` symlinked elsewhere in the
    # checkout resolves *out* of the install root, and a resolved-only
    # test would call it authored, publish it, and let autofixes rewrite
    # it. How it was reached makes it an install, not where the bytes
    # live.
    lexical = root_path.joinpath(*CODEX_INSTALL_DIR)
    try:
        if plugin_dir != lexical and plugin_dir.is_relative_to(lexical):
            return True
    except ValueError:  # pragma: no cover - defensive
        pass
    resolved = safe_resolve(plugin_dir)
    if resolved is None:
        return False
    return resolved != install_root and resolved.is_relative_to(install_root)
