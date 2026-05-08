"""Initialize a new Claude Code plugin marketplace."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional

from ..config import LinterConfig
from .branding import (
    COLOR_PRESETS,
    DEFAULT_COLOR_SCHEME,
    DEFAULT_MARKETPLACE_TYPE,
    MARKETPLACE_TYPES,
    apply_branding,
    apply_replacements,
    build_replacements,
    get_color_scheme,
    read_template,
    write_template_config,
)


def _prompt(prompt: str, default: str = "") -> str:
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result or default
    while True:
        result = input(f"{prompt}: ").strip()
        if result:
            return result
        print("Error: value is required")


def _prompt_color_scheme() -> Dict[str, str]:
    presets = list(COLOR_PRESETS.keys())
    print("\nColor scheme options:")
    for i, name in enumerate(presets, 1):
        colors = COLOR_PRESETS[name]
        print(f"  {i}) {name} ({colors['primary']})")
    print(f"  {len(presets) + 1}) custom")
    print()

    choice = _prompt("Choose a color scheme", "1")
    try:
        idx = int(choice) - 1
    except ValueError:
        idx = 0

    if 0 <= idx < len(presets):
        return COLOR_PRESETS[presets[idx]]
    elif idx == len(presets):
        return {
            "primary": _prompt("Primary color (hex)", "#6366f1"),
            "primary_dark": _prompt("Primary dark color (hex)", "#4f46e5"),
            "secondary": _prompt("Secondary color (hex)", "#818cf8"),
        }
    else:
        return COLOR_PRESETS[DEFAULT_COLOR_SCHEME]


def init_marketplace(
    path: Optional[Path] = None,
    name: Optional[str] = None,
    owner: Optional[str] = None,
    github_repo: Optional[str] = None,
    color_scheme: Optional[str] = None,
    marketplace_type: str = DEFAULT_MARKETPLACE_TYPE,
    no_example_plugin: bool = False,
    interactive: bool = False,
) -> Path:
    """Initialize a new marketplace at the given path."""
    root = (path or Path.cwd()).resolve()

    if marketplace_type not in MARKETPLACE_TYPES:
        print(
            f"Error: unsupported marketplace type: {marketplace_type!r}. "
            f"Available: {', '.join(MARKETPLACE_TYPES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if (root / ".claude-plugin" / "marketplace.json").exists():
        print("Error: marketplace already exists at this location", file=sys.stderr)
        sys.exit(1)

    if not interactive and (not name or not owner) and sys.stdin.isatty():
        interactive = True

    if interactive:
        if not name:
            name = _prompt("Marketplace name (e.g., 'my-plugins')")
        if not owner:
            owner = _prompt("Owner name (e.g., GitHub username)")
        if not github_repo:
            github_repo = _prompt("GitHub repository", f"{owner}/{name}")
        if not color_scheme:
            colors = _prompt_color_scheme()
        else:
            colors = get_color_scheme(color_scheme)

        keep_example = input("\nKeep example plugin? (Y/n): ").strip().lower()
        if keep_example == "n":
            no_example_plugin = True
    else:
        if not name:
            print("Error: --name is required (or use --interactive)", file=sys.stderr)
            sys.exit(1)
        if not owner:
            print("Error: --owner is required (or use --interactive)", file=sys.stderr)
            sys.exit(1)
        if not github_repo:
            github_repo = f"{owner}/{name}"
        colors = get_color_scheme(color_scheme or DEFAULT_COLOR_SCHEME)

    replacements = build_replacements(name, owner, github_repo, colors)

    _create_structure(root, replacements, marketplace_type)

    write_template_config(root, name, owner, github_repo, colors, marketplace_type)

    apply_branding(root, replacements)

    if not no_example_plugin:
        from .add import add_plugin

        add_plugin("example-plugin", path=root)

    print(f"\nMarketplace initialized: {root}")
    print("\nNext steps:")
    print("  skillsaw add plugin my-plugin    # Add a plugin")
    print("  skillsaw -v --strict             # Run linter")
    print("  skillsaw docs                    # Generate docs")
    if github_repo:
        print(f"  git remote add origin git@github.com:{github_repo}.git")

    return root


def _create_structure(
    root: Path,
    replacements: Dict[str, str],
    marketplace_type: str = DEFAULT_MARKETPLACE_TYPE,
) -> None:
    """Create all marketplace directories and files from templates."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / "plugins").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)

    t = marketplace_type

    _write(
        root / ".claude-plugin" / "marketplace.json",
        read_template("marketplace.json", t),
        replacements,
    )

    _write(root / ".claude-plugin" / "settings.json", read_template("settings.json", t))

    _write(root / "docs" / "index.html", read_template("index.html", t), replacements)

    (root / "docs" / ".nojekyll").touch()

    _write(root / "docs" / "README.md", read_template("docs_readme.md", t))

    _write(root / "README.md", read_template("marketplace_readme.md", t), replacements)

    _write(root / "Makefile", read_template("makefile", t), replacements)

    _write(root / ".github" / "workflows" / "lint.yml", read_template("lint.yml", t))

    LinterConfig.default().save(root / ".skillsaw.yaml")

    _write(root / ".gitignore", read_template("gitignore", t))


def _write(
    dest: Path,
    content: str,
    replacements: Optional[Dict[str, str]] = None,
) -> None:
    if replacements:
        content = apply_replacements(content, replacements)
    dest.write_text(content, encoding="utf-8")
