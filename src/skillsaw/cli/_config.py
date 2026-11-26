"""Config discovery, loading, and version helpers for the CLI."""

from __future__ import annotations

import dataclasses
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
    elif not getattr(args, "scratch_paths", False):
        config_path = find_config(start_path)
    # else: the paths are a directory skillsaw made, such as skills fetched
    # from MCP servers, whose ancestors (/tmp) anyone may write to. Its caller
    # already looked for a config where the user ran skillsaw.

    if config_path:
        try:
            config = LinterConfig.from_file(config_path)
        except ValueError as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
        _emit_config_warnings(config)
    else:
        config = LinterConfig.default()
    # Scratch MCP directories hold server-controlled paths unrelated to the
    # local checkout, so local exclude globs and content_paths must not hide
    # fetched skills. Unconfigured pulls likewise drop default template/cache
    # excludes so a server cannot evade linting under those segment names.
    if getattr(args, "scratch_paths", False):
        config.exclude_patterns = []
        config.content_paths = []
        for rule_cfg in config.rules.values():
            if isinstance(rule_cfg, dict) and "exclude" in rule_cfg:
                rule_cfg["exclude"] = []
        if config.codex_instructions is not None and config.codex_instructions.cwd != ".":
            config.codex_instructions = dataclasses.replace(config.codex_instructions, cwd=".")
    elif config_path is None:
        from ..formats.mcp_skills import read_valid_snapshot_record

        if read_valid_snapshot_record(start_path) is not None:
            config.exclude_patterns = []
    return config, config_path


def resolve_fail_level(args, config: LinterConfig) -> str:
    """Apply lint's CLI-over-config failure-threshold precedence."""
    if args.fail_on:
        return args.fail_on
    if args.strict:
        return "warning"
    return config.effective_fail_level()


def resolve_fix_level(args, config: LinterConfig) -> str:
    """The severity scope ``skillsaw fix`` repairs: what lint shows — errors
    and warnings, widened to everything by ``fail-on: info``. Naming rules
    with ``--rule`` is explicit intent, so those fix at any severity.

    Shared by the fix engine and the lint formatters, so a ``[*]``/``[?]``
    marker is always a finding a fix run will actually repair.
    """
    if args.rule_ids:
        return "info"
    return "info" if config.effective_fail_level() == "info" else "warning"
