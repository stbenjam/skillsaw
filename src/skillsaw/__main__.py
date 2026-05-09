"""
Entry point for skillsaw (and claudelint backward-compat shim)
"""

import argparse
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

from .context import RepositoryContext, RepositoryType
from .config import LinterConfig, find_config
from .linter import Linter
from .formatters import format_report, get_counts, infer_format, FORMATS
from . import __version__

_SUBCOMMANDS = {"lint", "init", "list-rules", "docs", "add", "enable", "disable", "bundles"}


def _get_version() -> str:
    try:
        return version("skillsaw")
    except PackageNotFoundError:
        return __version__


def main():
    # When no subcommand is given (or the first arg looks like a path/flag),
    # default to "lint" so bare `skillsaw` and `skillsaw /path` keep working.
    # `add` has its own argparse — dispatch before the main parser sees the args.
    if len(sys.argv) > 1 and sys.argv[1] == "add":
        from .marketplace.cli import _run_add_cli

        return _run_add_cli()

    if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS | {"--version", "-h", "--help"}:
        sys.argv.insert(1, "lint")

    parser = argparse.ArgumentParser(
        prog="skillsaw",
        description="Keep your skills sharp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  skillsaw                        # Lint current directory
  skillsaw lint /path/to/skills   # Lint specific directory
  skillsaw init                   # Generate default config
  skillsaw list-rules             # List available rules
  skillsaw bundles                # List available rule bundles
  skillsaw enable cursor          # Enable all Cursor rules
  skillsaw disable content        # Disable all content rules
  skillsaw enable cursor-mdc-valid  # Enable a single rule
  skillsaw docs                   # Generate documentation
  skillsaw add marketplace        # Scaffold a new marketplace

For more information, visit: https://github.com/stbenjam/skillsaw
        """,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")

    subparsers = parser.add_subparsers(dest="command")

    # --- lint ---
    lint_parser = subparsers.add_parser(
        "lint",
        help="Lint agent skills, plugins, and AI coding assistant context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    lint_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to skill, plugin, or marketplace directory (default: current directory)",
    )
    lint_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover)",
    )
    lint_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show info-level messages"
    )
    lint_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit with error code if warnings exist)",
    )
    lint_parser.add_argument(
        "--format",
        dest="fmt",
        default="text",
        choices=FORMATS,
        help="Output format for stdout (default: text)",
    )
    lint_parser.add_argument(
        "--output",
        dest="outputs",
        action="append",
        default=[],
        metavar="FILE",
        help="Write output to FILE (format inferred from extension: .json, .sarif, .html). "
        "Can be specified multiple times.",
    )

    # --- init ---
    init_parser = subparsers.add_parser(
        "init", help="Generate a default .skillsaw.yaml config file"
    )
    init_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory to create config in (default: current directory)",
    )

    # --- list-rules ---
    subparsers.add_parser("list-rules", help="List all available builtin rules")

    # --- docs ---
    docs_parser = subparsers.add_parser(
        "docs",
        help="Generate documentation for a plugin, marketplace, or .claude repository",
        description="Generate documentation for a plugin, marketplace, or .claude repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    docs_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to repository (default: current directory)",
    )
    docs_parser.add_argument(
        "--format",
        dest="fmt",
        default="html",
        choices=["html", "markdown"],
        help="Output format (default: html)",
    )
    docs_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file or directory (default: skillsaw-docs/). "
        "If it ends with .html/.md, writes a single file directly.",
    )
    docs_parser.add_argument("--title", default=None, help="Custom title for the documentation")

    # --- add ---
    subparsers.add_parser(
        "add",
        help="Scaffold marketplaces, plugins, skills, commands, agents, and hooks",
        add_help=False,
    )

    # --- enable ---
    enable_parser = subparsers.add_parser(
        "enable",
        help="Enable a rule or bundle in .skillsaw.yaml",
    )
    enable_parser.add_argument(
        "name",
        help="Rule ID or bundle name to enable",
    )
    enable_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory containing .skillsaw.yaml (default: current directory)",
    )
    enable_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )

    # --- disable ---
    disable_parser = subparsers.add_parser(
        "disable",
        help="Disable a rule or bundle in .skillsaw.yaml",
    )
    disable_parser.add_argument(
        "name",
        help="Rule ID or bundle name to disable",
    )
    disable_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory containing .skillsaw.yaml (default: current directory)",
    )
    disable_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )

    # --- bundles ---
    subparsers.add_parser(
        "bundles",
        help="List available rule bundles",
    )

    args = parser.parse_args()

    if args.command == "lint":
        _run_lint(args)
    elif args.command == "init":
        _run_init(args)
    elif args.command == "list-rules":
        _run_list_rules()
    elif args.command == "docs":
        _run_docs(args)
    elif args.command == "enable":
        _run_enable(args)
    elif args.command == "disable":
        _run_disable(args)
    elif args.command == "bundles":
        _run_bundles()


def _run_lint(args):
    cli_version = _get_version()

    output_formats = {}
    for output_path in args.outputs:
        try:
            output_formats[output_path] = infer_format(output_path)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    if args.fmt == "text":
        print(f"Linting: {args.path}\n")
    context = RepositoryContext(args.path)

    if context.repo_type == RepositoryType.UNKNOWN:
        print("Warning: Directory doesn't appear to be a recognized repository", file=sys.stderr)
        print(
            "Expected: .claude-plugin/plugin.json, plugins/ directory, or SKILL.md (agentskills.io)\n",
            file=sys.stderr,
        )

    if args.config:
        config_path = args.config
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = find_config(args.path)

    if config_path:
        try:
            config = LinterConfig.from_file(config_path)
            if args.verbose and args.fmt == "text":
                print(f"Using config: {config_path}\n")
        except ValueError as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        config = LinterConfig.default()

    if args.strict:
        config.strict = True

    linter = Linter(context, config)
    violations = linter.run()

    stdout_output = format_report(
        args.fmt, violations, context, linter.rules, cli_version, verbose=args.verbose
    )
    print(stdout_output)

    report_cache = {}
    for output_path, fmt in output_formats.items():
        if fmt not in report_cache:
            report_cache[fmt] = format_report(
                fmt, violations, context, linter.rules, cli_version, verbose=args.verbose
            )
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_cache[fmt], encoding="utf-8")

    errors, warnings_count, info = get_counts(violations)

    if errors > 0:
        sys.exit(1)
    elif config.strict and warnings_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


def _run_init(args):
    config_path = args.path / ".skillsaw.yaml"
    if config_path.exists():
        print(f"Config file already exists: {config_path}")
        sys.exit(1)

    config = LinterConfig.for_init()
    config.save(config_path)
    print(f"Created default config: {config_path}")
    sys.exit(0)


def _run_list_rules():
    from .rules.builtin import BUILTIN_RULES

    print("Available builtin rules:\n")
    for rule_class in BUILTIN_RULES:
        rule = rule_class()
        print(f"  {rule.rule_id}")
        print(f"    {rule.description}")
        print(f"    Default severity: {rule.default_severity().value}")
        print()
    sys.exit(0)


def _run_docs(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    context = RepositoryContext(args.path)

    if context.repo_type == RepositoryType.UNKNOWN:
        print("Warning: Directory doesn't appear to be a recognized repository", file=sys.stderr)
        print(
            "Expected: .claude-plugin/plugin.json, plugins/ directory, or SKILL.md (agentskills.io)\n",
            file=sys.stderr,
        )

    from .docs import extract_docs, render_html, render_markdown

    docs_output = extract_docs(context, title=args.title)

    if args.fmt == "html":
        pages = render_html(docs_output)
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


def _run_enable(args):
    from .bundles import resolve_names, enable_rules

    name = args.name
    rule_ids, was_bundle = resolve_names(name)

    if not rule_ids:
        print(f"Error: '{name}' is not a known rule or bundle.", file=sys.stderr)
        print("Run 'skillsaw bundles' to see available bundles.", file=sys.stderr)
        print("Run 'skillsaw list-rules' to see available rules.", file=sys.stderr)
        sys.exit(1)

    results = enable_rules(rule_ids, args.path, dry_run=args.dry_run)

    if was_bundle:
        enabled_count = sum(1 for _, action in results if action == "enabled")
        verb = "Would enable" if args.dry_run else "Enabled"
        print(f"{verb} {enabled_count} rule(s) in bundle '{name}':")
    else:
        verb = "Would enable" if args.dry_run else "Enabled"

    for rid, action in results:
        if action == "enabled":
            print(f"  {rid} ✓")
        else:
            print(f"  {rid} (already enabled)")

    if args.dry_run:
        print("\n(dry run — no changes written)")


def _run_disable(args):
    from .bundles import resolve_names, disable_rules

    name = args.name
    rule_ids, was_bundle = resolve_names(name)

    if not rule_ids:
        print(f"Error: '{name}' is not a known rule or bundle.", file=sys.stderr)
        print("Run 'skillsaw bundles' to see available bundles.", file=sys.stderr)
        print("Run 'skillsaw list-rules' to see available rules.", file=sys.stderr)
        sys.exit(1)

    results = disable_rules(rule_ids, args.path, dry_run=args.dry_run)

    if was_bundle:
        disabled_count = sum(1 for _, action in results if action == "disabled")
        verb = "Would disable" if args.dry_run else "Disabled"
        print(f"{verb} {disabled_count} rule(s) in bundle '{name}':")
    else:
        verb = "Would disable" if args.dry_run else "Disabled"

    for rid, action in results:
        if action == "disabled":
            print(f"  {rid} ✓")
        else:
            print(f"  {rid} (already disabled)")

    if args.dry_run:
        print("\n(dry run — no changes written)")


def _run_bundles():
    from .bundles import BUILTIN_BUNDLES, get_bundle_rules

    print("Available rule bundles:\n")
    for bundle_name, description in BUILTIN_BUNDLES.items():
        rules = get_bundle_rules(bundle_name)
        print(f"  {bundle_name} ({len(rules)} rules)")
        print(f"    {description}")
        for rid in rules:
            print(f"      - {rid}")
        print()
    sys.exit(0)


def claudelint_shim():
    """Backward-compat entry point for the 'claudelint' command"""
    print(
        "WARNING: 'claudelint' has been renamed to 'skillsaw'. "
        "Please update your scripts. The 'claudelint' command will be removed in a future release.",
        file=sys.stderr,
    )
    main()


if __name__ == "__main__":
    main()
