"""CLI package for skillsaw — dispatcher, parser, and subcommand handlers."""

from __future__ import annotations

import sys

from ._parser import _build_parser

_SUBCOMMANDS = {
    "lint",
    "init",
    "list-rules",
    "docs",
    "add",
    "fix",
    "tree",
    "baseline",
    "explain",
    "badge",
    "plugins",
    "mcp",
}


def main():
    from ._helpers import install_warning_display

    install_warning_display()

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
        sys.argv.insert(1, "lint")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "lint":
        from ._lint import _run_lint

        _run_lint(args)
    elif args.command == "fix":
        from ._fix import _run_fix

        _run_fix(args)
    elif args.command == "init":
        from ._simple import _run_init

        _run_init(args)
    elif args.command == "list-rules":
        from ._simple import _run_list_rules

        _run_list_rules()
    elif args.command == "plugins":
        from ._simple import _run_plugins

        _run_plugins()
    elif args.command == "explain":
        from ._explain import _run_explain

        _run_explain(args)
    elif args.command == "docs":
        from ._docs import _run_docs

        _run_docs(args)
    elif args.command == "baseline":
        from ._baseline import _run_baseline

        _run_baseline(args)
    elif args.command == "badge":
        from ._badge import _run_badge

        _run_badge(args)
    elif args.command == "tree":
        from ._tree import _run_tree

        _run_tree(args)
    elif args.command == "mcp":
        from ._mcp import _run_mcp

        _run_mcp(args)


def claudelint_shim():
    """Backward-compat entry point for the 'claudelint' command"""
    print(
        "WARNING: 'claudelint' has been renamed to 'skillsaw'. "
        "Please update your scripts. The 'claudelint' command will be removed in a future release.",
        file=sys.stderr,
    )
    main()
