"""Scaffold plugins, skills, commands, agents, and hooks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

from .branding import (
    DEFAULT_MARKETPLACE_TYPE,
    apply_replacements,
    load_template_config,
    read_template,
)

_KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def _validate_kebab(name: str, label: str) -> None:
    if not _KEBAB_RE.match(name):
        raise ValueError(f"{label} must be kebab-case (lowercase, hyphens): {name!r}")


# ---------------------------------------------------------------------------
# Context detection
# ---------------------------------------------------------------------------


def _find_marketplace_root(path: Path) -> Path:
    """Walk up from *path* to find the directory containing .claude-plugin/marketplace.json."""
    current = path.resolve()
    while True:
        if (current / ".claude-plugin" / "marketplace.json").exists():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError("No marketplace found. Run 'skillsaw add marketplace' first.")
        current = parent


def _find_single_plugin_root(path: Path) -> Optional[Path]:
    """Walk up to find a single-plugin repo (.claude-plugin/plugin.json without marketplace.json)."""
    current = path.resolve()
    while True:
        has_plugin = (current / ".claude-plugin" / "plugin.json").exists()
        has_marketplace = (current / ".claude-plugin" / "marketplace.json").exists()
        if has_plugin and not has_marketplace:
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


_DOT_CLAUDE_MARKERS = ("commands", "skills", "hooks", "agents", "rules")


def _find_dot_claude_root(path: Path) -> Optional[Path]:
    """Check if *path* itself contains a .claude/ directory with known markers.

    Unlike marketplace/plugin detection, this does NOT walk up the tree.
    Walking up would match ~/.claude/ in home directories, causing false positives.
    """
    resolved = path.resolve()
    dot_claude = resolved / ".claude"
    if dot_claude.is_dir():
        if any((dot_claude / m).is_dir() for m in _DOT_CLAUDE_MARKERS):
            return resolved
    return None


def _find_plugin_context(path: Path, plugin_name: Optional[str]) -> Tuple[Path, Path, str]:
    """Resolve the (root, plugin_dir, marketplace_type) for a component add.

    Handles four cases:
      1. Marketplace with --plugin specified: resolve via marketplace.json
      2. Single-plugin repo (no --plugin needed): use the repo root as plugin dir
      3. .claude/ directory repo: use .claude/ as the target directory
      4. Ambiguous: error with guidance
    """
    resolved = (path or Path.cwd()).resolve()

    # Check for marketplace first
    try:
        mp_root = _find_marketplace_root(resolved)
    except FileNotFoundError:
        mp_root = None

    # Check for single plugin
    sp_root = _find_single_plugin_root(resolved)

    # Check for .claude/ repo
    dc_root = _find_dot_claude_root(resolved)

    candidates = {r for r in (mp_root, sp_root, dc_root) if r is not None}
    if len(candidates) > 1:
        labels = []
        if mp_root:
            labels.append(f"marketplace at {mp_root}")
        if sp_root:
            labels.append(f"plugin at {sp_root}")
        if dc_root:
            labels.append(f".claude/ at {dc_root}")
        raise ValueError(
            f"Ambiguous context: found {', '.join(labels)}. Use --path to disambiguate."
        )

    if mp_root:
        if not plugin_name:
            mp_path = mp_root / ".claude-plugin" / "marketplace.json"
            data = json.loads(mp_path.read_text(encoding="utf-8"))
            plugins = data.get("plugins", [])
            if not plugins:
                raise FileNotFoundError(
                    "No plugins found in this marketplace. Run 'skillsaw add plugin' first."
                )
            if len(plugins) == 1:
                plugin_name = plugins[0]["name"]
            else:
                raise ValueError(
                    "Multiple plugins in this marketplace. Use --plugin to specify which one."
                )
        plugin_dir = _resolve_plugin_dir(mp_root, plugin_name)
        mp_type = _marketplace_type(mp_root)
        return mp_root, plugin_dir, mp_type

    if sp_root:
        mp_type = _marketplace_type(sp_root)
        return sp_root, sp_root, mp_type

    if dc_root:
        mp_type = _marketplace_type(dc_root)
        return dc_root, dc_root / ".claude", mp_type

    raise FileNotFoundError(
        "No plugin, marketplace, or .claude/ directory found. "
        "Run 'skillsaw add marketplace' or create a .claude/ directory first."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner_from_config(root: Path) -> str:
    config = load_template_config(root)
    if config:
        return config.get("owner_name", "TODO: Add author")
    mp_path = root / ".claude-plugin" / "marketplace.json"
    if mp_path.exists():
        data = json.loads(mp_path.read_text(encoding="utf-8"))
        owner = data.get("owner", {})
        if isinstance(owner, dict):
            return owner.get("name", "TODO: Add author")
    return "TODO: Add author"


def _marketplace_name(root: Path) -> str:
    config = load_template_config(root)
    if config:
        return config.get("marketplace_name", "")
    mp_path = root / ".claude-plugin" / "marketplace.json"
    if mp_path.exists():
        data = json.loads(mp_path.read_text(encoding="utf-8"))
        return data.get("name", "")
    return ""


def _marketplace_type(root: Path) -> str:
    config = load_template_config(root)
    if config:
        return config.get("marketplace_type", DEFAULT_MARKETPLACE_TYPE)
    return DEFAULT_MARKETPLACE_TYPE


def _register_plugin(root: Path, name: str, source: str, description: str) -> None:
    """Add a plugin entry to marketplace.json and settings.json."""
    mp_path = root / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    data.setdefault("plugins", [])
    if not any(p.get("name") == name for p in data["plugins"]):
        data["plugins"].append(
            {
                "name": name,
                "source": source,
                "description": description,
            }
        )
        mp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    settings_path = root / ".claude-plugin" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = {"installedPlugins": []}
    settings.setdefault("installedPlugins", [])
    if not any(p.get("name") == name for p in settings["installedPlugins"]):
        settings["installedPlugins"].append(
            {
                "name": name,
                "source": "local",
                "enabled": True,
            }
        )
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _resolve_plugin_dir(root: Path, plugin_name: str) -> Path:
    """Find the directory for an existing plugin."""
    mp_path = root / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    for entry in data.get("plugins", []):
        if entry["name"] == plugin_name:
            source = entry.get("source", f"./plugins/{plugin_name}")
            resolved = (root / source).resolve()
            if not resolved.is_relative_to(root.resolve()):
                raise ValueError(f"Plugin source {source!r} resolves outside marketplace root")
            return resolved
    raise FileNotFoundError(f"Plugin {plugin_name!r} not found in marketplace.json")


# ---------------------------------------------------------------------------
# Add functions
# ---------------------------------------------------------------------------


def add_plugin(
    name: str,
    path: Optional[Path] = None,
) -> Path:
    """Create a new plugin with scaffold structure and register it."""
    _validate_kebab(name, "Plugin name")
    root = _find_marketplace_root(path or Path.cwd())
    plugin_dir = root / "plugins" / name
    if plugin_dir.exists():
        raise FileExistsError(f"Plugin directory already exists: {plugin_dir}")

    owner = _owner_from_config(root)
    mp_name = _marketplace_name(root)
    mp_type = _marketplace_type(root)

    replacements = {
        "PLUGIN_NAME": name,
        "OWNER_NAME": owner,
        "MARKETPLACE_NAME": mp_name,
        "COMMAND_NAME": "example",
    }

    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".claude-plugin").mkdir()
    (plugin_dir / "commands").mkdir()
    (plugin_dir / "skills").mkdir()

    plugin_json = apply_replacements(read_template("plugin.json", mp_type), replacements)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(plugin_json, encoding="utf-8")

    command_md = apply_replacements(read_template("command.md", mp_type), replacements)
    (plugin_dir / "commands" / "example.md").write_text(command_md, encoding="utf-8")

    readme = apply_replacements(read_template("readme.md", mp_type), replacements)
    (plugin_dir / "README.md").write_text(readme, encoding="utf-8")

    _register_plugin(root, name, f"./plugins/{name}", "TODO: Add description")

    print(f"Created plugin: {name}")
    print(f"  {plugin_dir}/")
    return plugin_dir


def add_skill(
    name: str,
    plugin_name: Optional[str] = None,
    path: Optional[Path] = None,
) -> Path:
    """Add a skill to a plugin, .claude/ repo, or standalone directory."""
    _validate_kebab(name, "Skill name")

    try:
        _root, plugin_dir, mp_type = _find_plugin_context(path or Path.cwd(), plugin_name)
        base = plugin_dir / "skills"
    except FileNotFoundError:
        if plugin_name:
            raise
        base = (path or Path.cwd()).resolve()
        if (base / "skills").is_dir():
            base = base / "skills"
        mp_type = DEFAULT_MARKETPLACE_TYPE

    skill_dir = base / name
    if skill_dir.exists():
        raise FileExistsError(f"Skill directory already exists: {skill_dir}")

    display_name = name.replace("-", " ").title()
    replacements = {
        "SKILL_ID": name,
        "SKILL_NAME": display_name,
    }

    skill_dir.mkdir(parents=True)
    skill_md = apply_replacements(read_template("skill.md", mp_type), replacements)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    print(f"Created skill: {name}")
    print(f"  {skill_dir}/SKILL.md")
    return skill_dir


def add_command(
    name: str,
    plugin_name: Optional[str] = None,
    path: Optional[Path] = None,
) -> Path:
    """Add a command to an existing plugin."""
    _validate_kebab(name, "Command name")
    _root, plugin_dir, mp_type = _find_plugin_context(path or Path.cwd(), plugin_name)

    commands_dir = plugin_dir / "commands"
    commands_dir.mkdir(exist_ok=True)
    cmd_file = commands_dir / f"{name}.md"
    if cmd_file.exists():
        raise FileExistsError(f"Command already exists: {cmd_file}")

    # Derive plugin name from plugin.json if available
    pj_path = plugin_dir / ".claude-plugin" / "plugin.json"
    if pj_path.exists():
        pj = json.loads(pj_path.read_text(encoding="utf-8"))
        effective_plugin = pj.get("name", plugin_name or "plugin")
    else:
        effective_plugin = plugin_name or "plugin"

    replacements = {
        "PLUGIN_NAME": effective_plugin,
        "COMMAND_NAME": name,
    }

    command_md = apply_replacements(read_template("command.md", mp_type), replacements)
    cmd_file.write_text(command_md, encoding="utf-8")

    print(f"Created command: {name}")
    print(f"  {cmd_file}")
    return cmd_file


def add_agent(
    name: str,
    plugin_name: Optional[str] = None,
    path: Optional[Path] = None,
) -> Path:
    """Add an agent to an existing plugin."""
    _validate_kebab(name, "Agent name")
    _root, plugin_dir, mp_type = _find_plugin_context(path or Path.cwd(), plugin_name)

    agents_dir = plugin_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    agent_file = agents_dir / f"{name}.md"
    if agent_file.exists():
        raise FileExistsError(f"Agent already exists: {agent_file}")

    display_name = name.replace("-", " ").title()
    replacements = {
        "AGENT_NAME": display_name,
        "AGENT_ID": name,
    }

    agent_md = apply_replacements(read_template("agent.md", mp_type), replacements)
    agent_file.write_text(agent_md, encoding="utf-8")

    print(f"Created agent: {name}")
    print(f"  {agent_file}")
    return agent_file


_VALID_HOOK_EVENTS = {
    "SessionStart",
    "Setup",
    "InstructionsLoaded",
    "UserPromptSubmit",
    "UserPromptExpansion",
    "PreToolUse",
    "PermissionRequest",
    "PermissionDenied",
    "PostToolUse",
    "PostToolUseFailure",
    "PostToolBatch",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "TaskCreated",
    "TaskCompleted",
    "Stop",
    "StopFailure",
    "TeammateIdle",
    "ConfigChange",
    "CwdChanged",
    "FileChanged",
    "WorktreeCreate",
    "WorktreeRemove",
    "PreCompact",
    "PostCompact",
    "Elicitation",
    "ElicitationResult",
    "SessionEnd",
}


def add_hook(
    event: str,
    plugin_name: Optional[str] = None,
    path: Optional[Path] = None,
) -> Path:
    """Add a hook to an existing plugin.

    Creates a hook script and registers it in hooks/hooks.json.
    """
    if event not in _VALID_HOOK_EVENTS:
        raise ValueError(
            f"Unknown hook event: {event!r}. "
            f"Valid events: {', '.join(sorted(_VALID_HOOK_EVENTS))}"
        )

    _root, plugin_dir, _mp_type = _find_plugin_context(path or Path.cwd(), plugin_name)

    hooks_dir = plugin_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    # Create the hook script
    script_file = hooks_dir / f"{event}.sh"
    if script_file.exists():
        raise FileExistsError(f"Hook script already exists: {script_file}")

    script_file.write_text(
        f"#!/usr/bin/env bash\n"
        f"# Hook: {event}\n"
        f"# Input is provided via stdin as JSON.\n"
        f"#\n"
        f"# Exit codes:\n"
        f"#   0 — allow / continue\n"
        f"#   2 — block (PreToolUse only)\n"
        f"\n"
        f"exit 0\n",
        encoding="utf-8",
    )
    script_file.chmod(0o755)

    # Register in hooks.json
    hooks_json_path = hooks_dir / "hooks.json"
    if hooks_json_path.exists():
        data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
    else:
        data = {"hooks": {}}

    data.setdefault("hooks", {})
    data["hooks"].setdefault(event, [])
    hook_cmd = f"./hooks/{event}.sh"
    if not any(h.get("hooks", [{}])[0].get("command") == hook_cmd for h in data["hooks"][event]):
        data["hooks"][event].append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_cmd,
                    }
                ]
            }
        )
    hooks_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    print(f"Created hook: {event}")
    print(f"  {script_file}")
    print(f"  Registered in {hooks_json_path}")
    return script_file
