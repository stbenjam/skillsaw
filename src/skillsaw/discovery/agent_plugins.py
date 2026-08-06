"""State-free discovery for portable Agent Plugins packages."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Set

from skillsaw.formats.agent_plugins import is_agent_plugin_schema
from skillsaw.paths import contained_resolve, safe_is_dir, safe_is_file, safe_resolve
from skillsaw.utils import read_json, read_text

PLUGIN_MANIFEST = "plugin.json"
MCP_CONFIG = "mcp.json"

# A malformed JSON document cannot be parsed for its $schema, but an exact
# property/value spelling is still strong intent evidence. This deliberately
# does not match a URI merely mentioned in description text. The URI is
# captured from the property match itself so the returned value can never
# come from a different location in the file.
_SCHEMA_PROPERTY_RE = re.compile(
    r'"\$schema"\s*:\s*"(https://agent-plugins\.org/' r'schemas/[^"/]+/plugin\.schema\.json)"'
)


def declared_schema(path: Path, package_root: Path, kind: str) -> Optional[str]:
    """Return recognizable schema evidence from one contained JSON file.

    Discovery may inspect only files that resolve inside the prospective
    package. A symlink escape is a conformance error once the package is
    explicitly selected, never permission to read an external manifest.
    """
    root = safe_resolve(package_root)
    if root is None:
        return None
    resolved = contained_resolve(path, root)
    if resolved is None or not safe_is_file(resolved):
        return None

    data, error = read_json(resolved)
    if not error and isinstance(data, dict):
        # Well-formed JSON objects are judged solely by their parsed
        # top-level ``$schema``; a URI nested elsewhere (e.g. under
        # ``metadata``) is not a declaration.
        value = data.get("$schema")
        return value if is_agent_plugin_schema(value, kind) else None

    # The raw-content fallback exists only for documents the JSON parser
    # could not read as an object.
    content = read_text(resolved)
    if content and kind == "plugin":
        match = _SCHEMA_PROPERTY_RE.search(content)
        if match:
            return match.group(1)
    return None


def declares_agent_plugin(package_root: Path) -> bool:
    """Whether a directory carries positive Agent Plugins manifest evidence.

    ``mcp.json`` is an optional component, not the package entrypoint.  It
    therefore cannot opt an otherwise unrelated repository into this format;
    an explicit ``--type agent-plugin`` remains the escape hatch for linting a
    package whose manifest is missing or too malformed to identify itself.
    """
    return bool(declared_schema(package_root / PLUGIN_MANIFEST, package_root, "plugin"))


def discover_agent_plugins(root: Path, *, forced: bool = False) -> List[Path]:
    """Discover portable plugin roots at the lint root and ``plugins/*``.

    Agent Plugins defines a package, not a marketplace. ``plugins/*`` is the
    conventional collection layout used by public multi-package repositories;
    arbitrary recursive scanning would claim vendored or example manifests the
    caller did not ask to lint.
    """
    resolved_root = safe_resolve(root)
    if resolved_root is None:
        return []

    collection_children: List[Path] = []
    plugins_dir = root / "plugins"
    if safe_is_dir(plugins_dir) and contained_resolve(plugins_dir, resolved_root) is not None:
        try:
            collection_children = [
                child
                for child in sorted(plugins_dir.iterdir())
                if safe_is_dir(child) and contained_resolve(child, resolved_root) is not None
            ]
        except OSError:
            pass

    found: List[Path] = []
    seen: Set[Path] = set()
    for candidate in [root, *collection_children]:
        resolved = safe_resolve(candidate)
        if resolved is None or resolved in seen or not resolved.is_relative_to(resolved_root):
            continue
        if forced:
            # An explicit ``--type agent-plugin`` is the escape hatch for
            # packages whose manifests are missing or too malformed to
            # self-identify, so every collection member is validated. The
            # root joins only on its own declaration — a collection layout
            # already explains the repository, and seeding the root there
            # would fabricate a "missing root manifest" finding.
            if candidate == root and collection_children and not declares_agent_plugin(candidate):
                continue
        elif not declares_agent_plugin(candidate):
            continue
        found.append(candidate)
        seen.add(resolved)
    if forced and not found:
        # No collection evidence at all: seed the root so the manifest rule
        # can report the missing/unidentifiable package the caller asked for.
        return [root]
    return found


def discover_agent_plugin_skills(package_root: Path) -> List[Path]:
    """Discover only immediate, contained ``skills/*/SKILL.md`` entries."""
    root = safe_resolve(package_root)
    skills_dir = package_root / "skills"
    resolved_skills = contained_resolve(skills_dir, root) if root is not None else None
    if resolved_skills is None or not safe_is_dir(resolved_skills):
        return []

    found: List[Path] = []
    try:
        children = sorted(skills_dir.iterdir())
    except OSError:
        return found
    for child in children:
        resolved_child = contained_resolve(child, root)
        if resolved_child is None or not safe_is_dir(resolved_child):
            continue
        entrypoint = contained_resolve(child / "SKILL.md", root)
        if entrypoint is None or not safe_is_file(entrypoint):
            continue
        found.append(child)
    return found
