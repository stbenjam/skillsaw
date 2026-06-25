"""Handler for the ``skillsaw tree`` subcommand."""

from __future__ import annotations

import sys

from ..context import RepositoryContext
from ._config import load_config


def _run_tree(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    context = RepositoryContext(args.path)
    config, _config_path = load_config(args, args.path)

    context.content_paths = config.content_paths
    context.exclude_patterns = config.exclude_patterns
    context.apply_excludes()

    tree = context.lint_tree
    if args.fmt == "dot":
        print(tree.print_dot(root_path=context.root_path))
    else:
        print(tree.print_tree(root_path=context.root_path))
    sys.exit(0)
