"""CLI entry point for ``skillsaw add`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .branding import COLOR_PRESETS, DEFAULT_MARKETPLACE_TYPE, MARKETPLACE_TYPES, prompt_input

# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------


def _prompt_plugin_selection(path: Path) -> str:
    """List plugins from the nearest marketplace and prompt the user to pick one."""
    from .add import _find_marketplace_root

    root = _find_marketplace_root(path)
    mp_path = root / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp_path.read_text(encoding="utf-8"))
    plugins = data.get("plugins", [])

    print("\nAvailable plugins:")
    for i, p in enumerate(plugins, 1):
        desc = p.get("description", "")
        if desc:
            print(f"  {i}) {p['name']} — {desc}")
        else:
            print(f"  {i}) {p['name']}")
    print()

    while True:
        choice = input("Select plugin: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(plugins):
                return plugins[idx]["name"]
        except ValueError:
            for p in plugins:
                if p["name"] == choice:
                    return choice
        print("Invalid selection. Enter a number or plugin name.")


def _require_name(args_name: Optional[str], label: str, hint: str = "kebab-case") -> str:
    """Return the name, prompting interactively if missing and TTY is available."""
    if args_name:
        return args_name
    if sys.stdin.isatty():
        return prompt_input(f"{label} ({hint})")
    print(f"Error: {label.lower()} is required", file=sys.stderr)
    sys.exit(1)


def _handle_multi_plugin(exc: ValueError, callback, **kwargs) -> None:
    """If the error is about multiple plugins and we're on a TTY, prompt and retry."""
    if "Multiple plugins" not in str(exc) or not sys.stdin.isatty():
        raise exc
    path = kwargs.get("path") or Path.cwd()
    plugin = _prompt_plugin_selection(path)
    callback(plugin_name=plugin, **kwargs)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _run_add_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="skillsaw add",
        description="Scaffold marketplaces, plugins, skills, commands, agents, and hooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a new marketplace (interactive)
  skillsaw add marketplace

  # Create a marketplace with flags
  skillsaw add marketplace --name my-plugins --owner myuser

  # Add a plugin to a marketplace
  skillsaw add plugin my-plugin

  # Add a skill (prompts for name and plugin if needed)
  skillsaw add skill

  # Add a skill to a specific plugin
  skillsaw add skill my-skill --plugin my-plugin

  # Add a command to a plugin
  skillsaw add command greet --plugin my-plugin
        """,
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # --- marketplace ---
    mp_parser = subparsers.add_parser(
        "marketplace",
        help="Initialize a new marketplace",
    )
    mp_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="Directory to initialize (default: current directory)",
    )
    mp_parser.add_argument("--name", help="Marketplace name")
    mp_parser.add_argument("--owner", help="Owner name (e.g., GitHub username)")
    mp_parser.add_argument("--github-repo", help="GitHub repository (owner/repo)")
    mp_parser.add_argument(
        "--color-scheme",
        choices=list(COLOR_PRESETS.keys()),
        help="Color scheme preset",
    )
    mp_parser.add_argument(
        "--type",
        dest="marketplace_type",
        default=DEFAULT_MARKETPLACE_TYPE,
        choices=MARKETPLACE_TYPES,
        help=f"Marketplace type (default: {DEFAULT_MARKETPLACE_TYPE})",
    )
    mp_parser.add_argument(
        "--no-example-plugin",
        action="store_true",
        help="Do not create the example plugin",
    )
    mp_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt for missing values interactively",
    )

    # --- plugin ---
    plugin_parser = subparsers.add_parser("plugin", help="Add a new plugin")
    plugin_parser.add_argument("name", nargs="?", default=None, help="Plugin name (kebab-case)")
    plugin_parser.add_argument("--path", type=Path, default=None, help="Marketplace root path")

    # --- skill ---
    skill_parser = subparsers.add_parser("skill", help="Add a skill to a plugin")
    skill_parser.add_argument("name", nargs="?", default=None, help="Skill name (kebab-case)")
    skill_parser.add_argument(
        "--plugin",
        default=None,
        help="Target plugin name (auto-detected if unambiguous)",
    )
    skill_parser.add_argument("--path", type=Path, default=None, help="Marketplace root path")

    # --- command ---
    cmd_parser = subparsers.add_parser("command", help="Add a command to a plugin")
    cmd_parser.add_argument("name", nargs="?", default=None, help="Command name (kebab-case)")
    cmd_parser.add_argument(
        "--plugin",
        default=None,
        help="Target plugin name (auto-detected if unambiguous)",
    )
    cmd_parser.add_argument("--path", type=Path, default=None, help="Marketplace root path")

    # --- agent ---
    agent_parser = subparsers.add_parser("agent", help="Add an agent to a plugin")
    agent_parser.add_argument("name", nargs="?", default=None, help="Agent name (kebab-case)")
    agent_parser.add_argument(
        "--plugin",
        default=None,
        help="Target plugin name (auto-detected if unambiguous)",
    )
    agent_parser.add_argument("--path", type=Path, default=None, help="Marketplace root path")

    # --- hook ---
    hook_parser = subparsers.add_parser("hook", help="Add a hook to a plugin")
    hook_parser.add_argument(
        "event", nargs="?", default=None, help="Hook event name (e.g., UserPromptSubmit)"
    )
    hook_parser.add_argument(
        "--plugin",
        default=None,
        help="Target plugin name (auto-detected if unambiguous)",
    )
    hook_parser.add_argument("--path", type=Path, default=None, help="Marketplace root path")

    # --- apm ---
    apm_parser = subparsers.add_parser("apm", help="Scaffold a new APM package manifest (apm.yml)")
    apm_parser.add_argument("--name", help="Package name")
    apm_parser.add_argument("--version", default="0.1.0", help="Package version (default: 0.1.0)")
    apm_parser.add_argument("--description", help="Package description")
    apm_parser.add_argument("--author", help="Package author")
    apm_parser.add_argument("--license", dest="license_id", help="SPDX license identifier")
    apm_parser.add_argument(
        "--target",
        help="Target platform (e.g., claude, vscode, all)",
    )
    apm_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="Directory to create apm.yml in (default: current directory)",
    )

    args = parser.parse_args(sys.argv[2:])

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    try:
        if args.subcommand == "marketplace":
            from .init import init_marketplace

            init_marketplace(
                path=args.path,
                name=args.name,
                owner=args.owner,
                github_repo=args.github_repo,
                color_scheme=args.color_scheme,
                marketplace_type=args.marketplace_type,
                no_example_plugin=args.no_example_plugin,
                interactive=args.interactive,
            )

        elif args.subcommand == "plugin":
            from .add import add_plugin

            name = _require_name(args.name, "Plugin name")
            add_plugin(name=name, path=args.path)

        elif args.subcommand == "skill":
            from .add import add_skill

            name = _require_name(args.name, "Skill name")
            try:
                add_skill(name=name, plugin_name=args.plugin, path=args.path)
            except ValueError as exc:
                _handle_multi_plugin(exc, add_skill, name=name, path=args.path)

        elif args.subcommand == "command":
            from .add import add_command

            name = _require_name(args.name, "Command name")
            try:
                add_command(name=name, plugin_name=args.plugin, path=args.path)
            except ValueError as exc:
                _handle_multi_plugin(exc, add_command, name=name, path=args.path)

        elif args.subcommand == "agent":
            from .add import add_agent

            name = _require_name(args.name, "Agent name")
            try:
                add_agent(name=name, plugin_name=args.plugin, path=args.path)
            except ValueError as exc:
                _handle_multi_plugin(exc, add_agent, name=name, path=args.path)

        elif args.subcommand == "hook":
            from .add import add_hook

            event = _require_name(args.event, "Hook event", hint="e.g., SessionStart")
            try:
                add_hook(event=event, plugin_name=args.plugin, path=args.path)
            except ValueError as exc:
                _handle_multi_plugin(exc, add_hook, event=event, path=args.path)

        elif args.subcommand == "apm":
            from .add import add_apm

            add_apm(
                path=args.path,
                name=args.name,
                version=args.version,
                description=args.description,
                author=args.author,
                license_id=args.license_id,
                target=args.target,
            )

    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
