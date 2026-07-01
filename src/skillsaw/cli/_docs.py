"""Handler for the ``skillsaw docs`` subcommand."""

from __future__ import annotations

import sys
from pathlib import Path

from ..context import RepositoryContext, RepositoryType
from ._config import load_config


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

    if args.fmt == "html":
        pages = render_html(docs_output, theme=theme)
    else:
        pages = render_markdown(docs_output)

    output = args.output
    if output and output.suffix in (".html", ".md"):
        output.parent.mkdir(parents=True, exist_ok=True)
        combined = "\n".join(pages.values()) if len(pages) > 1 else next(iter(pages.values()))
        output.write_text(combined, encoding="utf-8")
        print(f"Documentation written to {output}")
    else:
        output_dir = output or Path("skillsaw-docs")
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in pages.items():
            (output_dir / filename).write_text(content, encoding="utf-8")
        file_list = ", ".join(sorted(pages.keys()))
        print(f"Documentation written to {output_dir}/ ({len(pages)} file(s): {file_list})")
