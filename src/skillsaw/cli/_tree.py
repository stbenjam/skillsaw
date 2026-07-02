"""Handler for the ``skillsaw tree`` subcommand."""

from __future__ import annotations

import sys

from ..context import RepositoryContext
from ._config import load_config


def _apply_plugin_extensions(context, config) -> None:
    """Register plugin repo types / tree contributors so the displayed tree
    matches what a lint run sees. Problems go to stderr — the tree itself
    must still print."""
    if not config.plugins_enabled:
        return
    from ..plugins import load_plugins, register_extensions

    plugins = load_plugins(disabled=set(config.disabled_plugins))
    for problem in register_extensions(context, plugins):
        print(f"Warning: {problem.message}", file=sys.stderr)


def _run_tree(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config, _config_path = load_config(args, args.path)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    _apply_plugin_extensions(context, config)

    tree = context.lint_tree
    if args.fmt == "dot":
        print(tree.print_dot(root_path=context.root_path))
    else:
        print(tree.print_tree(root_path=context.root_path))
    for message in context.plugin_extension_errors:
        print(f"Warning: {message}", file=sys.stderr)
    sys.exit(0)
