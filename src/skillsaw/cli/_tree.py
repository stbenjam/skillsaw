"""Handler for the ``skillsaw tree`` subcommand."""

from __future__ import annotations

import sys
from dataclasses import replace

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
    if (args.cwd is not None or args.fmt == "json") and not args.codex_instructions:
        print("Error: --cwd and --format json require --codex-instructions", file=sys.stderr)
        sys.exit(2)
    if args.codex_instructions and args.fmt == "dot":
        print("Error: --codex-instructions supports text or json", file=sys.stderr)
        sys.exit(2)
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config, _config_path = load_config(args, args.path)
    options = config.codex_instructions
    if args.codex_instructions:
        from ..formats.codex_instructions import CodexInstructionOptions

        options = options or CodexInstructionOptions()
        if args.cwd is not None:
            options = replace(options, cwd=args.cwd)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
        lint_external_content=config.lint_external_content,
        codex_instructions=options,
    )
    _apply_plugin_extensions(context, config)

    tree = context.lint_tree
    for message in context.plugin_extension_errors:
        print(f"Warning: {message}", file=sys.stderr)
    if context.lint_tree_errors:
        for message in context.lint_tree_errors:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)
    if args.codex_instructions:
        from ._codex_instructions import print_codex_instructions

        sys.exit(print_codex_instructions(context, args.fmt))
    elif args.fmt == "dot":
        print(tree.print_dot(root_path=context.root_path))
    else:
        print(tree.print_tree(root_path=context.root_path))
    sys.exit(0)
