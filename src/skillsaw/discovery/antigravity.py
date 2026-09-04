"""State-free discovery of Antigravity plugins and configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

from skillsaw.formats.agent_plugins import is_agent_plugin_schema
from skillsaw.formats.antigravity import (
    ANTIGRAVITY_CONFIG_DIR_NAMES,
    PLUGIN_MANIFEST,
)
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.utils import read_json


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
    if error or not isinstance(data, dict):
        return False
    schema = data.get("$schema")
    if is_agent_plugin_schema(schema, "plugin"):
        return False
    return True


def discover_antigravity_plugins(
    root: Path,
    *,
    forced: bool = False,
) -> List[Path]:
    """Return all directories identified as Antigravity plugins.

    Antigravity plugins are discovered ONLY in ``.agents/plugins/*``,
    ``.agent/plugins/*``, and ``_agents/plugins/*``.
    """
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    plugins: List[Path] = []
    seen: Set[Path] = set()

    def add_if_valid(p: Path) -> None:
        if contained_resolve(p, resolved_root) is None:
            return
        resolved = safe_resolve(p)
        if resolved is None or resolved in seen:
            return
        if not safe_is_dir(resolved):
            return
        seen.add(resolved)
        plugins.append(p)

    for config_dir_name in (*ANTIGRAVITY_CONFIG_DIR_NAMES, "_agents"):
        dot_plugins = root / config_dir_name / "plugins"
        if safe_is_dir(dot_plugins):
            try:
                for child in sorted(dot_plugins.iterdir()):
                    if safe_is_dir(child):
                        if forced:
                            if contained_resolve(child, resolved_root) is None:
                                continue
                            add_if_valid(child)
                        elif antigravity_manifest_is_contained(child):
                            add_if_valid(child)
            except OSError:
                pass

    return sorted(plugins)
