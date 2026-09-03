"""State-free discovery of Antigravity plugins and configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Set

from skillsaw.formats.agent_plugins import is_agent_plugin_schema
from skillsaw.formats.antigravity import (
    PLUGIN_MANIFEST,
    PLUGINS_CONFIG_FILENAME,
    SKILLS_CONFIG_FILENAME,
)
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.utils import read_json

ANTIGRAVITY_CONFIG_DIR_NAMES = (".agents", ".agent")


def antigravity_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries a contained ``plugin.json`` for Antigravity.

    Excludes files that declare the Agent Plugins specification schema.
    """
    resolved_root = safe_resolve(plugin_dir)
    if resolved_root is None:
        return False
    manifest = plugin_dir / PLUGIN_MANIFEST
    resolved_manifest = contained_resolve(manifest, resolved_root)
    if resolved_manifest is None or not safe_is_file(resolved_manifest):
        return False

    data, error = read_json(resolved_manifest)
    if not error and isinstance(data, dict):
        schema = data.get("$schema")
        if is_agent_plugin_schema(schema, "plugin"):
            return False
    return True


def enumerate_antigravity_local_sources(
    root: Path, plugins_json_paths: Iterable[Path]
) -> List[Path]:
    """Extract local plugin directory targets from discovered ``plugins.json`` files."""
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    sources: List[Path] = []
    seen: Set[Path] = set()

    for config_path in plugins_json_paths:
        data, error = read_json(config_path)
        if error or not isinstance(data, dict):
            continue
        entries = data.get("entries")
        if not isinstance(entries, list):
            continue
        base_dir = config_path.parent
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            candidate = (
                (base_dir / raw_path) if not Path(raw_path).is_absolute() else Path(raw_path)
            )
            resolved_candidate = contained_resolve(candidate, resolved_root)
            if (
                resolved_candidate is not None
                and resolved_candidate not in seen
                and safe_is_dir(resolved_candidate)
            ):
                seen.add(resolved_candidate)
                sources.append(resolved_candidate)

    return sorted(sources)


def discover_antigravity_plugins(
    root: Path,
    local_sources: Iterable[Path] = (),
    *,
    forced: bool = False,
) -> List[Path]:
    """Return all directories identified as Antigravity plugins."""
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    plugins: List[Path] = []
    seen: Set[Path] = set()

    def add_if_valid(p: Path) -> None:
        resolved = safe_resolve(p)
        if resolved is None or resolved in seen:
            return
        if not safe_is_dir(resolved):
            return
        seen.add(resolved)
        plugins.append(p)

    # 1. Root plugin
    if forced or antigravity_manifest_is_contained(root):
        add_if_valid(root)

    # 2. .agents/plugins/* and .agent/plugins/* subdirectories
    for config_dir_name in ANTIGRAVITY_CONFIG_DIR_NAMES:
        dot_plugins = root / config_dir_name / "plugins"
        if safe_is_dir(dot_plugins):
            try:
                for child in sorted(dot_plugins.iterdir()):
                    if safe_is_dir(child):
                        # Under .agents/plugins/, any folder or one with plugin.json is an Antigravity plugin
                        if (
                            forced
                            or antigravity_manifest_is_contained(child)
                            or safe_is_file(child / PLUGIN_MANIFEST)
                        ):
                            add_if_valid(child)
            except OSError:
                pass

    # 4. Catalog local sources
    for source in local_sources:
        add_if_valid(source)

    return sorted(plugins)


def discover_antigravity_configs(
    root: Path,
    tool_dirs: Optional[Mapping[str, Iterable[Path]]] = None,
) -> List[Path]:
    """Find ``skills.json`` and ``plugins.json`` files at the root or within config directories."""
    configs: List[Path] = []
    seen: Set[Path] = set()

    def add_config(p: Path) -> None:
        resolved = safe_resolve(p)
        if resolved is not None and resolved not in seen and safe_is_file(resolved):
            seen.add(resolved)
            configs.append(p)

    for filename in (SKILLS_CONFIG_FILENAME, PLUGINS_CONFIG_FILENAME):
        add_config(root / filename)
        for dir_name in ANTIGRAVITY_CONFIG_DIR_NAMES:
            add_config(root / dir_name / filename)

    if tool_dirs:
        for dir_name in ANTIGRAVITY_CONFIG_DIR_NAMES:
            for base in tool_dirs.get(dir_name) or ():
                for filename in (SKILLS_CONFIG_FILENAME, PLUGINS_CONFIG_FILENAME):
                    add_config(base / filename)

    return sorted(configs)
