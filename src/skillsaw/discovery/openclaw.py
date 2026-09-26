"""State-free native OpenClaw package discovery over the shared repository scan."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from skillsaw.formats.openclaw import MANIFEST, contained_file, read_package, read_package_text
from skillsaw.paths import Resolver, safe_exists, safe_is_symlink, safe_resolve, contained_resolve


def declares_extensions(path: Path) -> bool:
    """Package hook packs alone are not native plugins; extensions declare one."""
    # This one-shot evidence probe rejects ordinary packages without filling
    # the parsed-file cache or resolving every negative cache key. The context
    # caches discovery results; positive candidates use the shared JSON reader.
    content, error = read_package_text(path)
    if error:
        return False
    # Escaped keys are legal JSON too, so a backslash requires parsing.
    if not content or ('"openclaw"' not in content and "\\" not in content):
        return False
    data, _ = read_package(path)
    metadata = data.get("openclaw") if isinstance(data, dict) else None
    return isinstance(metadata, dict) and "extensions" in metadata


def claims_plugin(root: Path, *, resolve: Resolver = safe_resolve) -> bool:
    """Native markers and package extension declarations establish ownership.

    Even broken markers claim the directory, allowing a useful diagnostic
    without allowing their target to be read outside the plugin.
    """
    marker = root / MANIFEST
    if safe_exists(marker) or safe_is_symlink(marker):
        return True
    return contained_file(root, "package.json", resolve=resolve) and declares_extensions(
        root / "package.json"
    )


def discover_plugins(
    manifests: Iterable[Path], packages: Iterable[Path], excluded: Callable[[Path], bool]
) -> list[Path]:
    """Find native declarations without reading files outside their plugin."""
    roots: set[Path] = set()
    for path in (*manifests, *packages):
        if excluded(path) or excluded(path.parent):
            continue
        # A regular package.json is necessarily inside its resolved parent.
        # Resolve file containment only for symlinks, before reading them;
        # ordinary monorepos otherwise pay two realpath walks per package.
        if path.name != MANIFEST:
            if safe_is_symlink(path):
                root = safe_resolve(path.parent)
                if root is None or contained_resolve(path, root) is None:
                    continue
            if not declares_extensions(path):
                continue
        # A manifest symlink still declares a plugin; never read its target.
        if safe_resolve(path.parent) is not None:
            roots.add(path.parent)
    return sorted(roots)
