"""Port Claude Code and Codex plugins to Agent Plugins v1 packages.

Agent Plugins v1 (https://agent-plugins.org) is a portable plugin format:
a root ``plugin.json`` manifest, skills at ``skills/*/SKILL.md``, and an
optional root ``mcp.json``. The format coexists with client-specific
content, so porting is additive — this module only ever writes the two
root files and never modifies or removes the source format's files.
Commands, agents, and hooks stay behind as client-specific content that
Claude Code keeps reading.

A port is a plan first: :func:`plan_port` reads a plugin directory and
returns the files it would write plus notes about anything that cannot
carry over (an MCP transport the spec doesn't define, a name that needed
normalizing). Nothing touches disk until :func:`apply_plan` runs, and a
port is refused rather than overwriting a ``plugin.json`` it doesn't
recognize.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .formats.agent_plugins import is_agent_plugin_schema
from .utils import read_json

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

# Manifest metadata fields shared verbatim between the source formats and
# the Agent Plugins closed schema (spec §5.4).
_COPIED_STRING_FIELDS = ("version", "description", "homepage", "repository", "license")

# Spec §5.5: 1-64 chars of [a-z0-9.-], alphanumeric ends, no -- or ..
_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

# Claude MCP transport names → Agent Plugins transport names (spec §7.2.1).
# "ws" has no portable equivalent and its servers are skipped with a note.
_TRANSPORT_MAP = {
    "stdio": "stdio",
    "http": "streamable-http",
    "streamable-http": "streamable-http",
    "sse": "sse",
}

_CLAUDE_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"


@dataclass
class PortPlan:
    """Everything one package port would do, before it does it."""

    root: Path
    sources: List[str]  # manifest formats the plan was read from
    writes: Dict[str, str] = field(default_factory=dict)  # filename → content
    notes: List[str] = field(default_factory=list)  # informational
    skipped: Optional[str] = None  # reason the whole package was skipped


def plan_port(root: Path) -> PortPlan:
    """Plan porting the plugin at *root* to an Agent Plugins v1 package."""
    manifest, sources, notes = read_source_manifest(root)
    plan = PortPlan(root=root, sources=sources, notes=notes)

    if manifest is None:
        plan.skipped = "no readable .claude-plugin/plugin.json or .codex-plugin/plugin.json"
        return plan

    existing = read_json(root / "plugin.json")[0]
    if (root / "plugin.json").exists():
        if isinstance(existing, dict) and is_agent_plugin_schema(existing.get("$schema"), "plugin"):
            plan.skipped = "already an Agent Plugins package (plugin.json declares the schema)"
        else:
            plan.skipped = "a plugin.json not declaring the Agent Plugins schema already exists — refusing to overwrite"
        return plan

    plan.writes["plugin.json"] = _render_manifest(manifest, root, plan.notes)

    mcp = read_source_mcp(root)
    if mcp is not None:
        content = render_mcp(mcp, plan.notes)
        if content is not None:
            if (root / "mcp.json").exists():
                plan.notes.append("mcp.json already exists — leaving it untouched")
            else:
                plan.writes["mcp.json"] = content

    _note_client_specific_content(root, plan.notes)
    return plan


def apply_plan(plan: PortPlan) -> List[Path]:
    """Write a plan's files. Returns the paths written."""
    written = []
    for filename, content in plan.writes.items():
        path = plan.root / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


# ── Reading the source formats ──────────────────────────────────


def read_source_manifest(
    root: Path,
) -> Tuple[Optional[Dict[str, Any]], List[str], List[str]]:
    """Merge the Claude and Codex manifests at *root*, Claude values first."""
    notes: List[str] = []
    merged: Dict[str, Any] = {}
    sources: List[str] = []
    for label, rel in (
        ("claude", ".claude-plugin/plugin.json"),
        ("codex", ".codex-plugin/plugin.json"),
    ):
        path = root / rel
        if not path.is_file():
            continue
        data, error = read_json(path)
        if error or not isinstance(data, dict):
            notes.append(f"{rel} could not be parsed and was ignored")
            continue
        sources.append(label)
        for key, value in data.items():
            merged.setdefault(key, value)
    if not sources:
        return None, sources, notes
    return merged, sources, notes


def read_source_mcp(root: Path) -> Optional[Dict[str, Any]]:
    """Return the source ``mcpServers`` mapping, if the plugin has one."""
    data, error = read_json(root / ".mcp.json")
    if error or not isinstance(data, dict):
        return None
    servers = data.get("mcpServers")
    return servers if isinstance(servers, dict) else None


# ── Manifest translation ────────────────────────────────────────


def _render_manifest(source: Dict[str, Any], root: Path, notes: List[str]) -> str:
    manifest: Dict[str, Any] = {"$schema": PLUGIN_SCHEMA}

    raw_name = source.get("name") if isinstance(source.get("name"), str) else root.name
    name = normalize_name(raw_name) or normalize_name(root.name) or "ported-plugin"
    if name != raw_name:
        notes.append(
            f"name {raw_name!r} does not satisfy the Agent Plugins name rules — using {name!r}"
        )
    manifest["name"] = name

    for key in _COPIED_STRING_FIELDS:
        value = source.get(key)
        if isinstance(value, str) and value:
            manifest[key] = value

    author = source.get("author")
    if isinstance(author, str) and author:
        manifest["author"] = {"name": author}
    elif isinstance(author, dict):
        kept = {
            k: v for k, v in author.items() if k in ("name", "email", "url") and isinstance(v, str)
        }
        dropped = sorted(set(author) - set(kept))
        if kept:
            manifest["author"] = kept
        if dropped:
            notes.append(
                f"author field(s) {', '.join(dropped)} have no Agent Plugins equivalent and were dropped"
            )

    keywords = source.get("keywords")
    if isinstance(keywords, list) and all(isinstance(k, str) for k in keywords) and keywords:
        manifest["keywords"] = keywords

    return json.dumps(manifest, indent=2) + "\n"


def normalize_name(name: str) -> Optional[str]:
    """Coerce a source name into the spec's name constraints (§5.5)."""
    if _NAME_RE.match(name) and len(name) <= 64:
        return name
    candidate = re.sub(r"[^a-z0-9.-]+", "-", name.lower())
    candidate = re.sub(r"-{2,}", "-", candidate)
    candidate = re.sub(r"\.{2,}", ".", candidate)
    candidate = candidate.strip("-.")[:64].strip("-.")
    return candidate if candidate and _NAME_RE.match(candidate) else None


# ── MCP translation ─────────────────────────────────────────────


def render_mcp(servers: Dict[str, Any], notes: List[str]) -> Optional[str]:
    """Translate a Claude ``mcpServers`` mapping to the portable format."""
    ported: Dict[str, Any] = {}
    for name, config in servers.items():
        if not isinstance(config, dict):
            notes.append(f"MCP server '{name}' is not an object and was skipped")
            continue
        entry = _port_server(name, config, notes)
        if entry is not None:
            ported[name] = entry
    if not ported:
        if servers:
            notes.append("no MCP servers could be ported — mcp.json not written")
        return None
    return json.dumps({"$schema": MCP_SCHEMA, "mcpServers": ported}, indent=2) + "\n"


def _port_server(name: str, config: Dict[str, Any], notes: List[str]) -> Optional[Dict[str, Any]]:
    source_type = config.get("type", "stdio" if "command" in config else None)
    target_type = _TRANSPORT_MAP.get(source_type)
    if target_type is None:
        notes.append(
            f"MCP server '{name}' uses transport {source_type!r}, which Agent Plugins does not define — skipped"
        )
        return None

    if target_type == "stdio":
        command = config.get("command")
        if not isinstance(command, str) or not command:
            notes.append(f"MCP server '{name}' has no usable 'command' — skipped")
            return None
        # Spec §7.2.1: command is one executable token, bare or ./-relative,
        # with no placeholder expansion. The Claude root variable at the
        # front of a path is exactly a plugin-relative reference.
        if command.startswith(_CLAUDE_ROOT_VAR + "/"):
            command = "./" + command[len(_CLAUDE_ROOT_VAR) + 1 :]
        if _CLAUDE_ROOT_VAR in command or " " in command:
            notes.append(
                f"MCP server '{name}' 'command' is not a single plain executable token — skipped"
            )
            return None
        entry: Dict[str, Any] = {"type": "stdio", "command": command}
        args = config.get("args")
        if isinstance(args, list) and all(isinstance(a, str) for a in args):
            entry["args"] = [_port_placeholders(a) for a in args]
        env = config.get("env")
        if isinstance(env, dict):
            if any(k in ("PLUGIN_ROOT", "PLUGIN_DATA") for k in env):
                notes.append(
                    f"MCP server '{name}' env defines a reserved Agent Plugins variable — skipped"
                )
                return None
            entry["env"] = {k: _port_placeholders(v) for k, v in env.items() if isinstance(v, str)}
        cwd = config.get("cwd")
        if isinstance(cwd, str) and cwd:
            entry["cwd"] = _port_placeholders(cwd)
        return entry

    url = config.get("url")
    if not isinstance(url, str) or not url:
        notes.append(f"MCP server '{name}' has no usable 'url' — skipped")
        return None
    entry = {"type": target_type, "url": url}
    headers = config.get("headers")
    if isinstance(headers, dict):
        entry["headers"] = {k: v for k, v in headers.items() if isinstance(v, str)}
    return entry


def _port_placeholders(value: str) -> str:
    return value.replace(_CLAUDE_ROOT_VAR, "${PLUGIN_ROOT}")


# ── Notes about what stays behind ───────────────────────────────


def _note_client_specific_content(root: Path, notes: List[str]) -> None:
    behind = [d + "/" for d in ("commands", "agents", "hooks") if (root / d).is_dir()]
    if behind:
        notes.append(
            f"{', '.join(behind)} stay as client-specific content — "
            "Agent Plugins v1 defines only skills and MCP servers"
        )
    skills = root / "skills"
    if not skills.is_dir():
        notes.append("no skills/ directory — the package ports with no portable components")
