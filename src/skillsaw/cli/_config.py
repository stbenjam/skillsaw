"""Config discovery, loading, and version helpers for the CLI."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..config import LinterConfig, find_config
from .. import __version__


def _get_version() -> str:
    try:
        return version("skillsaw")
    except PackageNotFoundError:
        return __version__


def _emit_config_warnings(config) -> None:
    """Print non-fatal config-load warnings (missing version, unknown keys)."""
    for warning in getattr(config, "warnings", []):
        print(f"Warning: {warning}", file=sys.stderr)


def load_config(args, start_path: Path) -> tuple[LinterConfig, Path | None]:
    """Discover and load the skillsaw config, returning (config, config_path).

    Checks ``args.config`` when present, otherwise auto-discovers from
    *start_path*.  Exits on missing or invalid config files.
    """
    config_path = getattr(args, "config", None)
    if config_path is not None:
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = find_config(start_path)

    if config_path:
        try:
            config = LinterConfig.from_file(config_path)
        except ValueError as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
        _emit_config_warnings(config)
    else:
        config = LinterConfig.default()
    return config, config_path
