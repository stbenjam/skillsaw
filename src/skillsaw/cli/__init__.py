"""CLI package for skillsaw — dispatcher, parser, and subcommand handlers."""

from __future__ import annotations

import sys
from pathlib import Path

from ._parser import _build_parser

_SUBCOMMANDS = {
    "lint",
    "init",
    "feedback",
    "list-rules",
    "add",
    "fix",
    "tree",
    "baseline",
    "explain",
    "badge",
    "plugins",
    "port",
    "pull",
}

_DEPRECATED_COMMANDS = frozenset({"add"})

# Commands removed in a release stay reserved: falling through to the
# implicit lint path would run `skillsaw lint docs --output site.html` and
# overwrite the page an old CI step meant to generate. A plugin registering
# the name still wins, like any other plugin subcommand.
_REMOVED_COMMANDS = {"docs": "0.21.0"}


def _warn_deprecated_command(command: str) -> None:
    print(
        f"Warning: 'skillsaw {command}' is deprecated and will be removed "
        "in an upcoming release.",
        file=sys.stderr,
    )


def _exit_removed_command(command: str) -> None:
    print(
        f"Error: 'skillsaw {command}' was removed in {_REMOVED_COMMANDS[command]}. "
        "It generated repository documentation and has no replacement; see "
        "https://skillsaw.org/upgrading-0.21/. To lint a directory named "
        f"'{command}', run 'skillsaw lint {command}'.",
        file=sys.stderr,
    )
    sys.exit(2)


def _tolerate_unencodable_output() -> None:
    """Never let a report die on a codepoint the console cannot encode.

    A report quotes whatever the repository holds — an em dash, a check
    mark, a lone surrogate escape — and a redirected Windows console or a
    ``PYTHONIOENCODING=cp1252`` environment cannot encode all of it. With
    the default ``strict`` handler the whole run ends in a traceback and no
    ``--output`` file is written. Replacing the unencodable character keeps
    the report and its exit code; the character shows as ``?``.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass


def _served_skills(parser, args, *, paths_given: bool) -> bool:
    """Whether the command runs over skills fetched from MCP servers."""
    if args.mcp_servers or args.mcp_config:
        if paths_given:
            parser.error(
                "--mcp-server and --mcp-config take the place of a path; "
                "run local paths separately"
            )
        return True
    if args.mcp_headers:
        parser.error("--mcp-header needs a --mcp-server URL")
    return False


def main():
    from ._helpers import install_warning_display

    _tolerate_unencodable_output()
    install_warning_display()

    if len(sys.argv) > 1 and sys.argv[1] in _DEPRECATED_COMMANDS:
        _warn_deprecated_command(sys.argv[1])

    # When no subcommand is given (or the first arg looks like a path/flag),
    # default to "lint" so bare `skillsaw` and `skillsaw /path` keep working.
    # `add` has its own argparse — dispatch before the main parser sees the args.
    if len(sys.argv) > 1 and sys.argv[1] == "add":
        from ..marketplace.cli import _run_add_cli

        return _run_add_cli()

    if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS | {"--version", "-h", "--help"}:
        # Plugin subcommands: `skillsaw <name> ...` runs skillsaw-<name> when
        # <name> is a registered plugin. Builtins above always win; anything
        # unmatched falls through to the implicit lint-path behavior.
        if len(sys.argv) > 1:
            from ._extensions import find_plugin_command, run_plugin_command

            exe = find_plugin_command(sys.argv[1])
            if exe is not None:
                sys.exit(run_plugin_command(exe, sys.argv[1], sys.argv[2:]))
            if sys.argv[1] in _REMOVED_COMMANDS:
                _exit_removed_command(sys.argv[1])
        sys.argv.insert(1, "lint")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "lint":
        if _served_skills(parser, args, paths_given=bool(args.path)):
            from ._mcp_skills import _run_lint_mcp_skills

            _run_lint_mcp_skills(args)
            return
        from ._lint import _run_lint

        _run_lint(args)
    elif args.command == "fix":
        from ._fix import _run_fix

        _run_fix(args)
    elif args.command == "init":
        from ._simple import _run_init

        _run_init(args)
    elif args.command == "feedback":
        from ._feedback import _run_feedback

        _run_feedback(args)
    elif args.command == "list-rules":
        from ._simple import _run_list_rules

        _run_list_rules()
    elif args.command == "plugins":
        from ._simple import _run_plugins

        _run_plugins()
    elif args.command == "explain":
        from ._explain import _run_explain

        _run_explain(args)
    elif args.command == "baseline":
        from ._baseline import _run_baseline

        _run_baseline(args)
    elif args.command == "badge":
        from ._badge import _run_badge

        _run_badge(args)
    elif args.command == "port":
        from ._port import _run_port

        _run_port(args)
    elif args.command == "tree":
        if _served_skills(parser, args, paths_given=args.path is not None):
            from ._mcp_skills import _run_tree_mcp_skills

            _run_tree_mcp_skills(args)
            return
        from ._tree import _run_tree

        if args.path is None:
            args.path = Path.cwd()
        _run_tree(args)
    elif args.command == "pull":
        if not (args.mcp_servers or args.mcp_config):
            parser.error("pull needs --mcp-server or --mcp-config")
        from ._mcp_skills import _run_pull

        _run_pull(args)


def claudelint_shim():
    """Backward-compat entry point for the 'claudelint' command"""
    print(
        "WARNING: 'claudelint' has been renamed to 'skillsaw'. "
        "Please update your scripts. The 'claudelint' command will be removed in a future release.",
        file=sys.stderr,
    )
    main()
