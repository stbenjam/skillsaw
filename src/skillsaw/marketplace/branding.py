"""Color presets and placeholder substitution for marketplace branding."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, Optional

COLOR_PRESETS = {
    "forest-green": {
        "primary": "#228B22",
        "primary_dark": "#1a6b1a",
        "secondary": "#32CD32",
    },
    "ocean-blue": {
        "primary": "#0077be",
        "primary_dark": "#005a8e",
        "secondary": "#4db8ff",
    },
    "sunset-orange": {
        "primary": "#ff6b35",
        "primary_dark": "#d94f1f",
        "secondary": "#ff9966",
    },
    "royal-purple": {
        "primary": "#6a4c93",
        "primary_dark": "#4a3369",
        "secondary": "#9d84b7",
    },
    "crimson-red": {
        "primary": "#dc143c",
        "primary_dark": "#a0102a",
        "secondary": "#ff6b7a",
    },
}

DEFAULT_COLOR_SCHEME = "forest-green"

DEFAULT_MARKETPLACE_TYPE = "claude-code"
MARKETPLACE_TYPES = [DEFAULT_MARKETPLACE_TYPE]


def read_template(name: str, marketplace_type: str = DEFAULT_MARKETPLACE_TYPE) -> str:
    """Read a template file from the package templates directory for the given type."""
    return (
        files("skillsaw.marketplace.templates")
        .joinpath(marketplace_type)
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def get_color_scheme(preset: str) -> Dict[str, str]:
    """Get a color scheme by preset name. Raises ValueError for unknown presets."""
    if preset not in COLOR_PRESETS:
        raise ValueError(
            f"Unknown color scheme: {preset!r}. " f"Available: {', '.join(COLOR_PRESETS)}"
        )
    return COLOR_PRESETS[preset]


def build_replacements(
    name: str,
    owner: str,
    github_repo: str,
    color_scheme: Dict[str, str],
) -> Dict[str, str]:
    """Build the placeholder->value mapping for template substitution."""
    if "/" in github_repo:
        gh_owner, repo = github_repo.split("/", 1)
        github_pages_url = f"{gh_owner}.github.io/{repo}"
    else:
        github_pages_url = f"{github_repo}.github.io"

    return {
        "MARKETPLACE_NAME": name,
        "MARKETPLACE_TITLE": f"{name} - Claude Code Plugins",
        "MARKETPLACE_SUBTITLE": f"Claude Code Plugins by {owner}",
        "OWNER_NAME": owner,
        "GITHUB_REPO": github_repo,
        "GITHUB_PAGES_URL": github_pages_url,
        "PRIMARY_COLOR": color_scheme["primary"],
        "PRIMARY_DARK": color_scheme["primary_dark"],
        "SECONDARY_COLOR": color_scheme["secondary"],
    }


def apply_replacements(content: str, replacements: Dict[str, str]) -> str:
    """Apply {{PLACEHOLDER}} substitutions to a string."""
    for key, value in replacements.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def apply_branding(root: Path, replacements: Optional[Dict[str, str]] = None) -> None:
    """Apply branding to generated marketplace files.

    If replacements is None, reads them from .template-config.json.
    """
    if replacements is None:
        config = load_template_config(root)
        if config is None:
            return
        color = config.get("color_scheme", COLOR_PRESETS[DEFAULT_COLOR_SCHEME])
        replacements = build_replacements(
            name=config["marketplace_name"],
            owner=config["owner_name"],
            github_repo=config["github_repo"],
            color_scheme=color,
        )

    branded_files = [
        root / "docs" / "index.html",
        root / "README.md",
        root / ".claude-plugin" / "marketplace.json",
    ]

    for file_path in branded_files:
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            content = apply_replacements(content, replacements)
            file_path.write_text(content, encoding="utf-8")


def write_template_config(
    root: Path,
    name: str,
    owner: str,
    github_repo: str,
    color_scheme: Dict[str, str],
    marketplace_type: str = DEFAULT_MARKETPLACE_TYPE,
) -> None:
    """Write .template-config.json to the marketplace root."""
    config = {
        "template_version": "1.0.0",
        "marketplace_type": marketplace_type,
        "marketplace_name": name,
        "owner_name": owner,
        "github_repo": github_repo,
        "color_scheme": color_scheme,
    }
    config_path = root / ".template-config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def load_template_config(root: Path) -> Optional[Dict[str, Any]]:
    """Load .template-config.json from the marketplace root."""
    config_path = root / ".template-config.json"
    if not config_path.exists():
        return None
    return json.loads(config_path.read_text(encoding="utf-8"))
