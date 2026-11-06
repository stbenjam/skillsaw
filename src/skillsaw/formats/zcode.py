"""Z.ai ZCode vocabulary: plugin manifests, catalogs, hooks, and ``.zcode/``.

ZCode's loader is open source (``zai-org/ZCode``). Every constant here is
read off that source at commit ``a9fe401e`` (v3.17.2), with the file and line
cited beside it, so a maintainer can re-check a value against the loader
rather than against prose. The paths below are relative to
``apps/zcode-cli/packages/``.

ZCode packages and installs plugins the way Claude Code does, and reads
Claude's files as fallbacks: a plugin manifest from ``.zcode-plugin/``,
then ``.claude-plugin/``, then ``.codex-plugin/``; a marketplace catalog
from ``.claude-plugin/marketplace.json``, then the repository root's
``marketplace.json``. skillsaw claims only the spellings that are ZCode's
alone — ``.zcode-plugin/plugin.json``, and the root ``marketplace.json`` of a
repository that ships ZCode plugins — because claiming Claude's files would
put every Claude plugin under ZCode's format rules too.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from skillsaw.paths import (
    Resolver,
    contained_resolve,
    marker_escapes,
    marker_manifest_is_contained,
    safe_is_dir,
    safe_is_file,
    safe_resolve,
)
from skillsaw.utils import read_json

# -- Plugins -----------------------------------------------------------------

#: ZCode's own plugin marker directory and the manifest inside it
#: (``adapters/src/plugins/index.ts:105``).
PLUGIN_DIR_NAME = ".zcode-plugin"
PLUGIN_MANIFEST = "plugin.json"

#: Where a plugin manifest may live, in the order ZCode resolves them; the
#: first that exists wins (``adapters/src/plugins/index.ts:935-948``).
MANIFEST_PATHS = (
    (PLUGIN_DIR_NAME, PLUGIN_MANIFEST),
    (".claude-plugin", PLUGIN_MANIFEST),
    (".codex-plugin", PLUGIN_MANIFEST),
)

#: Plugin and marketplace names ZCode accepts
#: (``adapters/src/plugins/index.ts:111``, ``marketplace.ts:68-69``). Looser
#: than Claude's kebab-case: dots and underscores are allowed. ``\Z`` rather
#: than ``$`` because ZCode trims the name first, and ``$`` would accept a
#: trailing newline that JavaScript's anchor rejects.
NAME_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,127}\Z")

#: Manifest components ZCode recognises but does not load. Each one produces
#: a ``plugin_unsupported_component`` warning and is otherwise ignored
#: (``adapters/src/plugins/index.ts:112``, ``:378-390``).
UNSUPPORTED_COMPONENT_KEYS = ("channels", "lspServers", "outputStyles", "settings")

#: Manifest fields holding one path or an array of paths, each resolved
#: against the plugin root and rejected when absolute or ``..``-escaping
#: (``adapters/src/plugins/helpers.ts:6-22``). ``hooks`` and ``mcpServers``
#: may also hold an inline object, or an array mixing both forms
#: (``hook-sources.ts:42-99``, ``mcp.ts:71-97``).
PATH_FIELDS = ("skills", "commands", "agents", "hooks", "mcpServers")

#: Conventional component locations ZCode reads with no manifest field at
#: all; declared paths are *added* to these, never substituted
#: (``adapters/src/plugins/index.ts:677-714``, ``hook-sources.ts:8``,
#: ``mcp.ts:26``).
CONVENTIONAL_HOOKS = ("hooks", "hooks.json")
CONVENTIONAL_MCP = ".mcp.json"

#: The name a manifest-object command must normalise to
#: (``adapters/src/plugins/index.ts:813-817``): leading slashes stripped and
#: lowercased first.
COMMAND_NAME_RE = re.compile(r"\A[a-z0-9][a-z0-9_:-]{0,63}\Z")

# -- Hooks -------------------------------------------------------------------

#: The hook events ZCode runs (``contracts/src/hooks/index.ts:7-15``). An
#: event outside this set is skipped with a warning; the rest of the file
#: still loads (``adapters/src/plugins/index.ts:522-532``).
HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
    }
)

#: Handler types ZCode accepts (``contracts/src/hooks/index.ts:393-419``).
#: Claude's ``prompt``, ``agent``, ``http`` and ``mcp_tool`` handlers fail
#: the discriminated union, which drops the whole matcher group around them.
HOOK_TYPES = ("command", "process")

# -- Marketplace catalogs ----------------------------------------------------

#: The catalog filename. ZCode reads ``.claude-plugin/marketplace.json``
#: first and the root file only when that is absent
#: (``adapters/src/plugins/marketplace.ts:2359-2370``); the official ZCode
#: marketplace (``zai-org/zcode-plugins``) publishes the root spelling.
MARKETPLACE_FILENAME = "marketplace.json"
CLAUDE_CATALOG = (".claude-plugin", MARKETPLACE_FILENAME)

#: Object ``source`` kinds ZCode resolves without cloning anything
#: (``adapters/src/plugins/marketplace.ts:1441-1447``). Remote kinds are
#: fetched at install time and are outside a static lint.
REMOTE_SOURCE_KINDS = frozenset({"github", "git", "url", "git-subdir"})
#: The non-empty string fields each object source kind requires; a missing
#: one fails the install (``adapters/src/plugins/marketplace.ts:1444-1498``).
SOURCE_REQUIRED_FIELDS = {
    "directory": ("path",),
    "github": ("repo",),
    "git": ("url",),
    "url": ("url",),
    "git-subdir": ("path", "url"),
}
#: Kinds ZCode recognises and refuses (``marketplace.ts:1501-1503``).
UNSUPPORTED_SOURCE_KINDS = frozenset({"npm", "pip"})

# -- The project layer -------------------------------------------------------

#: The project directory ZCode reads, in every directory from the session's
#: working directory up to the git root (``adapters/src/skills/roots.ts``,
#: ``adapters/src/commands/roots.ts``). ``~/.zcode`` is the user-level
#: counterpart and never appears in a lint.
TOOL_DIR_NAME = ".zcode"
SKILLS_DIR_NAME = "skills"
#: Read recursively, ``*.md`` (``adapters/src/commands/index.ts:236-262``).
COMMANDS_DIR_NAME = "commands"
#: Read flat, ``*.md`` or ``*.markdown`` (``bootstrap/src/subagents.ts:57``,
#: ``:302-318``).
AGENTS_DIR_NAME = "agents"
AGENT_GLOBS = ("*.md", "*.markdown")
#: ZCode reads subagent frontmatter one ``key: value`` line at a time, not
#: as YAML, so frontmatter a YAML parser rejects can still load
#: (``packages/shared/src/subagent-profile-frontmatter.ts:80-95``).
_AGENT_FRONTMATTER_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")
#: Project configuration (``packages/shared/src/workspace-hook-config.ts:178-183``).
#: Its sibling ``zcode.json`` is deliberately not read: the name is generic
#: enough that unrelated tools commit files called that.
CONFIG_FILENAME = "config.json"


def zcode_manifest_is_contained(plugin_dir: Path, *, resolve: Resolver = safe_resolve) -> bool:
    """Whether *plugin_dir* carries a ``.zcode-plugin/plugin.json`` of its own.

    ``.zcode-plugin`` only, never the Claude or Codex fallbacks: those are
    another ecosystem's declaration, and reading them as ZCode evidence
    would put every Claude plugin under ZCode's format rules.
    """
    return marker_manifest_is_contained(
        plugin_dir, PLUGIN_DIR_NAME, PLUGIN_MANIFEST, resolve=resolve
    )


def zcode_marker_escapes(plugin_dir: Path, *, resolve: Resolver = safe_resolve) -> bool:
    """Whether *plugin_dir*'s ``.zcode-plugin`` marker points out of the plugin."""
    return marker_escapes(plugin_dir, PLUGIN_DIR_NAME, PLUGIN_MANIFEST, resolve=resolve)


def zcode_manifest_path(plugin_dir: Path) -> Optional[Path]:
    """The manifest ZCode loads for *plugin_dir*, following :data:`MANIFEST_PATHS`.

    Contained: a manifest that resolves outside the plugin is another
    plugin's, so it is not this one's answer.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return None
    for parts in MANIFEST_PATHS:
        candidate = plugin_dir.joinpath(*parts)
        if contained_resolve(candidate, root) is not None and safe_is_file(candidate):
            return candidate
    return None


def zcode_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """*plugin_dir*'s parsed manifest, or ``{}`` when absent or unparseable."""
    path = zcode_manifest_path(plugin_dir)
    if path is None:
        return {}
    data, error = read_json(path)
    return data if not error and isinstance(data, dict) else {}


def path_list(value: Any) -> List[str]:
    """The strings a path field names, as ZCode's ``parsePathList`` reads them.

    One string, or the strings in an array; anything else names no path
    (``adapters/src/plugins/helpers.ts:18-22``).
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def lexically_escapes(value: str) -> bool:
    """Whether ZCode's ``resolveInside`` rejects *value* outright.

    An absolute path, or one whose normalised form climbs out of the plugin
    root (``adapters/src/plugins/helpers.ts:6-12``). Symlinks are not
    followed by that check, so this is lexical, as it is.
    """
    if value.startswith(("/", "\\")) or re.match(r"\A[A-Za-z]:[\\/]", value):
        return True
    depth = 0
    for part in value.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def zcode_declared_paths(plugin_dir: Path, field: str, *, want_dir: bool) -> List[Path]:
    """Contained paths the manifest names in *field*, deduplicated.

    Paths ZCode rejects (absolute or escaping) are dropped here, and the
    manifest rule reports them; so is any path that does not exist as the
    kind *want_dir* asks for.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return []
    found: List[Path] = []
    seen: Set[Path] = set()
    for raw in path_list(zcode_manifest(plugin_dir).get(field)):
        if lexically_escapes(raw):
            continue
        candidate = contained_resolve(plugin_dir / raw, root)
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        if safe_is_dir(candidate) if want_dir else safe_is_file(candidate):
            found.append(candidate)
    return found


def zcode_command_source_files(plugin_dir: Path) -> List[Path]:
    """Contained ``source`` files of an object-form ``commands`` map.

    ZCode reads each entry's ``source`` (one leading ``./`` stripped) and
    writes it out as a command (``adapters/src/plugins/index.ts:716-811``).
    """
    commands = zcode_manifest(plugin_dir).get("commands")
    root = safe_resolve(plugin_dir)
    if not isinstance(commands, dict) or root is None:
        return []
    found: List[Path] = []
    seen: Set[Path] = set()
    for entry in commands.values():
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, str) or not source:
            continue
        relative = source[2:] if source.startswith("./") else source
        if lexically_escapes(relative):
            continue
        candidate = contained_resolve(plugin_dir / relative, root)
        if candidate is not None and safe_is_file(candidate) and candidate not in seen:
            seen.add(candidate)
            found.append(plugin_dir / relative)
    return found


def zcode_declared_skill_dirs(plugin_dir: Path) -> List[Path]:
    """Skill roots a manifest adds through ``skills``."""
    return zcode_declared_paths(plugin_dir, "skills", want_dir=True)


def zcode_declared_hook_files(plugin_dir: Path) -> List[Path]:
    """Hook files a manifest names through ``hooks``."""
    return zcode_declared_paths(plugin_dir, "hooks", want_dir=False)


def zcode_declared_mcp_files(plugin_dir: Path) -> List[Path]:
    """MCP config files a manifest names through ``mcpServers``."""
    return zcode_declared_paths(plugin_dir, "mcpServers", want_dir=False)


def zcode_inline_hooks(plugin_dir: Path) -> List[Dict[str, Any]]:
    """Hooks written inline in the manifest, one ``{"hooks": ...}`` document each.

    ZCode reads an inline ``hooks`` object as the event map itself, with no
    ``hooks`` wrapper (``adapters/src/plugins/hook-sources.ts:94-98``,
    ``index.ts:502-506``), so each object is wrapped as-is: an event that
    happens to be named ``hooks`` stays an (unsupported) event.
    """
    declared = zcode_manifest(plugin_dir).get("hooks")
    items = declared if isinstance(declared, list) else [declared]
    return [{"hooks": item} for item in items if isinstance(item, dict)]


def zcode_inline_mcp(plugin_dir: Path) -> List[Dict[str, Any]]:
    """MCP servers written inline in the manifest.

    A bare server map or a ``{"mcpServers": {...}}`` wrapper, alone or in an
    array. ZCode takes a nested ``mcpServers`` object whenever there is one,
    whatever its siblings (``adapters/src/plugins/mcp.ts:121-139``).
    """
    declared = zcode_manifest(plugin_dir).get("mcpServers")
    items = declared if isinstance(declared, list) else [declared]
    return [
        {"mcpServers": item["mcpServers"] if isinstance(item.get("mcpServers"), dict) else item}
        for item in items
        if isinstance(item, dict)
    ]


def catalog_plugin_base(marketplace_root: Path, data: Dict[str, Any]) -> Path:
    """The directory a catalog's local sources resolve against.

    The marketplace root, or ``metadata.pluginRoot`` inside it when that
    names an existing directory (``adapters/src/plugins/marketplace.ts:1651-1658``).
    """
    metadata = data.get("metadata")
    plugin_root = metadata.get("pluginRoot") if isinstance(metadata, dict) else None
    if isinstance(plugin_root, str) and plugin_root and not lexically_escapes(plugin_root):
        candidate = marketplace_root / plugin_root
        if safe_is_dir(candidate):
            return candidate
    return marketplace_root


def catalog_entries(data: Any) -> List[Any]:
    """A catalog's plugin entries, as ZCode reads ``plugins``.

    An array, or an object keyed by plugin name whose values gain that name
    (``adapters/src/plugins/marketplace.ts:2181-2198``); anything else is no
    plugins at all.
    """
    if not isinstance(data, dict):
        return []
    plugins = data.get("plugins")
    if isinstance(plugins, list):
        return list(plugins)
    if isinstance(plugins, dict):
        return [
            {"name": name, **entry} if isinstance(entry, dict) else {"name": name}
            for name, entry in plugins.items()
        ]
    return []


def entry_local_source(entry: Dict[str, Any], base: Path) -> Optional[Path]:
    """The checkout directory a catalog entry installs from, or ``None``.

    A string source is a path under *base* (one leading ``./`` stripped); an
    entry with no source falls back to ``<base>/<name>``
    (``adapters/src/plugins/marketplace.ts:1434-1441``, ``:1509-1511``).
    Object sources name a remote repository or an absolute directory, and
    are not this checkout's.
    """
    source = entry.get("source")
    if isinstance(source, str):
        if source in ("filesystem", "sea"):
            return None  # bundled-plugin seed values, not paths
        relative = source[2:] if source.startswith("./") else source
        if lexically_escapes(relative):
            return None
        return base / relative
    if source is None:
        name = entry.get("name")
        if isinstance(name, str) and name.strip() and not lexically_escapes(name.strip()):
            return base / name.strip()
    return None


def _strip_inline_comment(value: str) -> str:
    """Drop a ``#`` comment that follows whitespace outside quotes."""
    quote = None
    for index, char in enumerate(value):
        if char in "\"'" and (index == 0 or value[index - 1] != "\\"):
            quote = None if quote == char else (quote or char)
        if not quote and char == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].rstrip()
    return value


def _zcode_string_scalar(raw: str) -> Optional[str]:
    """The string ZCode's line reader makes of *raw*, or None for a non-string.

    Mirrors ``parseScalarValue`` (``subagent-profile-frontmatter.ts:156-204``):
    ``true``, ``false``, digits, ``[...]`` and ``{...}`` become other types, and
    an empty value starts a list.
    """
    value = _strip_inline_comment(raw.strip())
    if not value or value in ("true", "false") or value.isdigit():
        return None
    if (value[0], value[-1]) in (("[", "]"), ("{", "}")):
        return None
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def zcode_agent_line_values(frontmatter: str) -> Dict[str, Tuple[Optional[str], int]]:
    """Scalar ``key: value`` lines as ZCode's line reader sees them.

    Maps each key to its string value (None when ZCode reads another type)
    and its 1-based line within *frontmatter*; the last line for a key wins.
    """
    values: Dict[str, Tuple[Optional[str], int]] = {}
    for number, line in enumerate(frontmatter.splitlines(), start=1):
        match = _AGENT_FRONTMATTER_LINE_RE.match(line.rstrip())
        if match:
            values[match.group(1)] = (_zcode_string_scalar(match.group(2)), number)
    return values
