"""Handler for the ``skillsaw docs`` subcommand."""

from __future__ import annotations

import sys
from pathlib import Path

from ..context import RepositoryContext, RepositoryType
from ..paths import safe_resolve
from ..utils import write_bytes_atomic
from ._config import load_config


def _docs_output_root(output: Path) -> Path:
    """Resolve the output parent so lexical and anchored paths agree."""
    resolved_root = safe_resolve(output.parent)
    if resolved_root is None:
        raise OSError(f"Could not resolve documentation output root: {output.parent}")
    return resolved_root


def _run_docs(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config, _config_path = load_config(args, args.path)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )

    if context.repo_type == RepositoryType.UNKNOWN:
        print("Warning: Directory doesn't appear to be a recognized repository", file=sys.stderr)
        print(
            "Expected: .claude-plugin/plugin.json, plugins/ directory, or SKILL.md (agentskills.io)\n",
            file=sys.stderr,
        )

    from ..docs import extract_docs, render_html, render_markdown
    from ..docs.html_renderer import COLOR_THEMES

    theme = args.theme
    if theme and theme not in COLOR_THEMES:
        print(
            f"Error: Unknown theme '{theme}'. " f"Available: {', '.join(sorted(COLOR_THEMES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    docs_output = extract_docs(context, title=args.title)
    if context.lint_tree_errors:
        for message in context.lint_tree_errors:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    if args.fmt == "html":
        pages = render_html(docs_output, theme=theme)
    else:
        pages = render_markdown(docs_output)

    output = args.output
    try:
        if output and output.suffix in (".html", ".md"):
            output.parent.mkdir(parents=True, exist_ok=True)
            output_root = _docs_output_root(output)
            write_path = output_root / output.name
            combined = "\n".join(pages.values()) if len(pages) > 1 else next(iter(pages.values()))
            write_bytes_atomic(write_path, combined.encode("utf-8"), root=output_root)
            print(f"Documentation written to {output}")
        else:
            output_dir = output or Path("skillsaw-docs")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_root = _docs_output_root(output_dir)
            write_dir = output_root / output_dir.name
            for filename, content in pages.items():
                write_bytes_atomic(
                    write_dir / filename,
                    content.encode("utf-8"),
                    root=output_root,
                )
            file_list = ", ".join(sorted(pages.keys()))
            print(f"Documentation written to {output_dir}/ ({len(pages)} file(s): {file_list})")
    except OSError as exc:
        print(f"Error: Could not write documentation: {exc}", file=sys.stderr)
        sys.exit(1)
