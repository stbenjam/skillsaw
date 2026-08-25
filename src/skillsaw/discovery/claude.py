"""State-free Claude plugin and Agent Skill filesystem discovery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from skillsaw.discovery import (
    CONVENTIONAL_SKILL_DIRS,
    agent_plugins as agent_plugins_discovery,
    exact_name_exists,
)
from skillsaw.formats.codex import codex_declared_skill_dirs
from skillsaw.paths import contained_resolve, safe_exists, safe_is_dir, safe_resolve

logger = logging.getLogger(__name__)


@dataclass
class PluginDiscovery:
    """Claude plugin paths plus metadata collected during discovery."""

    paths: List[Path] = field(default_factory=list)
    metadata: Dict[Path, Dict[str, Any]] = field(default_factory=dict)
    entries: Dict[Path, Dict[str, Any]] = field(default_factory=dict)
    escaped: List[Path] = field(default_factory=list)


def load_marketplace(root: Path) -> Optional[Dict[str, Any]]:
    """Load the root Claude marketplace mapping when it is readable."""
    path = root / ".claude-plugin" / "marketplace.json"
    try:
        with path.open() as stream:
            data = json.load(stream)
            return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def marketplace_plugin_root(data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return a non-empty marketplace ``pluginRoot`` value, if present."""
    metadata = data.get("metadata") if data else None
    value = metadata.get("pluginRoot") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and value else None


def resolve_plugin_source(
    root: Path, data: Optional[Dict[str, Any]], source: Any, entry: Dict[str, Any]
) -> Optional[Path]:
    """Resolve a contained local Claude marketplace source, if any."""
    name = entry.get("name", "unknown")
    if isinstance(source, str):
        resolved_root = safe_resolve(root)
        if resolved_root is None:
            logger.warning("Repository root cannot be resolved. Skipping plugin '%s'.", name)
            return None
        candidate = contained_resolve(resolved_root / source, resolved_root)
        plugin_root = marketplace_plugin_root(data)
        if plugin_root and not Path(source).is_absolute():
            composed = contained_resolve(resolved_root / plugin_root / source, resolved_root)
            if composed is not None and (
                safe_exists(composed) or candidate is None or not safe_exists(candidate)
            ):
                candidate = composed
            elif composed is None and (candidate is None or not safe_exists(candidate)):
                candidate = None
        if candidate is None:
            logger.warning(
                "Plugin '%s' source '%s' is unresolved or escapes repository root. Skipping.",
                name,
                source,
            )
            return None
        if not safe_exists(candidate) or not safe_is_dir(candidate):
            return None
        return candidate
    if isinstance(source, dict):
        logger.info("Plugin '%s' uses remote source. Skipping local validation.", name)
    else:
        logger.info("Plugin '%s' has unknown source format. Skipping.", name)
    return None


def is_valid_plugin_dir(path: Path, entry: Optional[Dict[str, Any]] = None) -> bool:
    """Return whether a directory has plugin content or relaxed metadata."""
    markers = (
        path / ".claude-plugin",
        path / "commands",
        path / "agents",
        path / "skills",
        path / "hooks",
    )
    return any(marker.exists() for marker in markers) or bool(
        entry is not None and entry.get("strict", True) is False
    )


def plugin_name(path: Path, metadata: Dict[Path, Dict[str, Any]]) -> str:
    """Return the manifest, marketplace, or directory name for a plugin."""
    manifest = path / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        try:
            with manifest.open() as stream:
                data = json.load(stream)
            name = data.get("name") if isinstance(data, dict) else None
            if isinstance(name, str) and name:
                return name
        except (json.JSONDecodeError, OSError):
            pass
    name = metadata.get(safe_resolve(path) or path, {}).get("name")
    return name if isinstance(name, str) else path.name


def plugin_metadata(
    path: Path,
    fallback: Dict[Path, Dict[str, Any]],
    entries: Dict[Path, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Merge a plugin manifest with its Claude marketplace metadata."""
    metadata: Dict[str, Any] = {}
    manifest = path / ".claude-plugin" / "plugin.json"
    if manifest.exists():
        try:
            with manifest.open() as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                metadata = data
        except (json.JSONDecodeError, OSError):
            pass
    resolved = safe_resolve(path) or path
    for source in (fallback.get(resolved, {}), entries.get(resolved, {})):
        for key, value in source.items():
            if key not in ("source", "strict") and key not in metadata:
                metadata[key] = value
    return metadata or None


def discover_plugins(
    root: Path,
    *,
    single_plugin: bool,
    dot_claude: bool,
    marketplace: bool,
    codex_enabled: bool,
    marketplace_data: Optional[Dict[str, Any]],
) -> PluginDiscovery:
    """Discover Claude-style plugin roots and marketplace metadata."""
    result = PluginDiscovery()
    seen: Set[Path] = set()

    def add(path: Path) -> None:
        """Append a resolved plugin path once."""
        resolved = safe_resolve(path)
        if resolved is not None and resolved not in seen:
            result.paths.append(path)
            seen.add(resolved)

    if single_plugin:
        add(root)
    if dot_claude and not marketplace:
        add(root if root.name == ".claude" else root / ".claude")
    if marketplace or codex_enabled:
        plugins_dir = root / "plugins"
        if plugins_dir.is_dir():
            try:
                for item in plugins_dir.iterdir():
                    if not item.is_dir() or item.name.startswith("."):
                        continue
                    if not is_valid_plugin_dir(item):
                        continue
                    if contained_resolve(item, root) is None:
                        logger.warning(
                            "Plugin '%s' source '%s' escapes repository root. Skipping.",
                            item.name,
                            f"./plugins/{item.name}",
                        )
                        result.escaped.append(item)
                        continue
                    add(item)
            except OSError:
                pass

        entries = marketplace_data.get("plugins") if marketplace_data else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("source"):
                    continue
                path = resolve_plugin_source(root, marketplace_data, entry["source"], entry)
                if path is None:
                    continue
                resolved = safe_resolve(path)
                if resolved is None:
                    continue
                result.entries[resolved] = entry
                if (
                    entry.get("strict", True) is False
                    and not (path / ".claude-plugin" / "plugin.json").exists()
                ):
                    result.metadata[resolved] = entry
                if resolved not in seen and is_valid_plugin_dir(path, entry):
                    add(path)
    return result


def discover_skills(
    root: Path,
    *,
    agentskills: bool,
    plugins: Iterable[Path],
    codex_plugins: Iterable[Path],
    agent_plugins: Iterable[Path],
    recursive_agent_plugins: Iterable[Path],
    in_apm_compiled_dir: Callable[[Path], bool],
    should_skip: Callable[[Path], bool],
    claim_boundary: Callable[[Path], Optional[Path]],
    containment_claims_possible: Callable[[], bool],
    is_containment_plugin: Callable[[Path], bool],
) -> List[Path]:
    """Discover contained Agent Skill directories across repository roots."""
    skills: List[Path] = []
    discovered: Set[Path] = set()
    agent_plugin_packages = list(agent_plugins)
    agent_plugin_roots = {
        resolved
        for plugin in agent_plugin_packages
        if (resolved := safe_resolve(plugin)) is not None
    }
    recursive_agent_plugin_roots = {
        resolved
        for plugin in recursive_agent_plugins
        if (resolved := safe_resolve(plugin)) is not None
    }
    agent_plugin_immediate_only = agent_plugin_roots - recursive_agent_plugin_roots

    def walk(
        parent: Path,
        boundary: Optional[Path] = None,
        visited: Optional[Set[Path]] = None,
    ) -> None:
        """Walk one skill collection without crossing its claim boundary."""
        resolved_parent = safe_resolve(parent)
        skip_subtrees: Set[Path] = set()
        if resolved_parent is not None and resolved_parent in agent_plugin_immediate_only:
            if visited is not None:
                # Mid-walk descent into a portable package: Agent Plugins has
                # a fixed, one-level skill scan below; the generic recursive
                # walk must not pull extension-private or otherwise nested
                # SKILL.md files into the portable package.
                return
            # The walk *starts* at a portable package root — the package is
            # the repository (or collection) root itself. Suppressing the
            # whole walk would silently drop every SKILL.md outside the
            # package's skills/ component, so only that component keeps the
            # fixed one-level semantics (the dedicated scan below owns it)
            # while the rest of the tree keeps recursive discovery.
            skills_component = safe_resolve(parent / "skills")
            if skills_component is not None:
                skip_subtrees.add(skills_component)
        if visited is None:
            visited = set()
            if boundary is None:
                boundary = claim_boundary(parent)
        try:
            for item in parent.iterdir():
                if should_skip(item):
                    continue
                resolved = safe_resolve(item)
                if resolved is None or resolved in discovered or resolved in visited:
                    continue
                if resolved in agent_plugin_immediate_only or resolved in skip_subtrees:
                    continue
                if boundary is not None and not resolved.is_relative_to(boundary):
                    continue
                if exact_name_exists(item, "SKILL.md"):
                    if boundary is not None:
                        entrypoint = safe_resolve(item / "SKILL.md")
                        if entrypoint is None or not entrypoint.is_relative_to(boundary):
                            continue
                    skills.append(item)
                    discovered.add(resolved)
                else:
                    visited.add(resolved)
                    child_boundary = boundary
                    if (
                        child_boundary is None
                        and containment_claims_possible()
                        and is_containment_plugin(item)
                    ):
                        child_boundary = resolved
                    walk(item, child_boundary, visited)
        except OSError:
            return

    if agentskills:
        if exact_name_exists(root, "SKILL.md"):
            skills.append(root)
            discovered.add(root)
        else:
            walk(root)
        for rel in CONVENTIONAL_SKILL_DIRS:
            path = root / rel
            if path.is_dir() and not in_apm_compiled_dir(path):
                walk(path)
    for plugin in plugins:
        path = plugin / "skills"
        if path.is_dir():
            walk(path)
    for plugin in codex_plugins:
        plugin_root = safe_resolve(plugin)
        if plugin_root is None:
            continue
        for path in (plugin / "skills", *codex_declared_skill_dirs(plugin)):
            if not path.is_dir():
                continue
            if exact_name_exists(path, "SKILL.md"):
                resolved = contained_resolve(path, plugin_root)
                if (
                    resolved is not None
                    and contained_resolve(path / "SKILL.md", plugin_root) is not None
                    and resolved not in discovered
                ):
                    skills.append(path)
                    discovered.add(resolved)
            else:
                walk(path, plugin_root)
    for plugin in agent_plugin_packages:
        for skill in agent_plugins_discovery.discover_agent_plugin_skills(plugin):
            resolved = safe_resolve(skill)
            if resolved is not None and resolved not in discovered:
                skills.append(skill)
                discovered.add(resolved)
    return skills
