"""
Entry point for skillsaw (and claudelint backward-compat shim)
"""

import argparse
import logging
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

from .context import RepositoryContext, RepositoryType
from .config import LinterConfig, find_config
from .linter import Linter
from .rule import Severity
from .formatters import format_report, get_counts, infer_format, FORMATS
from . import __version__

_SUBCOMMANDS = {"lint", "init", "list-rules", "docs", "add", "fix"}


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
        "--fix",
        action="store_true",
        help="Automatically fix violations where possible (applies safe fixes)",
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

    # --- fix ---
    fix_parser = subparsers.add_parser(
        "fix",
        help="Automatically fix lint violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fix_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to repository (default: current directory)",
    )
    fix_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file",
    )
    fix_parser.add_argument(
        "--llm",
        "--ai",
        action="store_true",
        dest="use_llm",
        help="Use LLM-powered fixes for content violations",
    )
    fix_parser.add_argument(
        "--model",
        help="Override LLM model (default: from config or claude-sonnet-4-20250514)",
    )
    fix_parser.add_argument(
        "--max-iterations",
        type=int,
        help="Max fix iterations per file (default: 3)",
    )
    fix_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-apply changes without confirmation",
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

    args = parser.parse_args()

    if args.command == "lint":
        _run_lint(args)
    elif args.command == "fix":
        _run_fix(args)
    elif args.command == "init":
        _run_init(args)
    elif args.command == "list-rules":
        _run_list_rules()
    elif args.command == "docs":
        _run_docs(args)


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

    if args.fix:
        violations, fixes = linter.fix()
        applied = linter.apply_fixes(fixes)
        if applied and args.fmt == "text":
            print(f"Fixed {len(applied)} issue(s):")
            for fix in applied:
                print(f"  ✓ [{fix.file_path}] {fix.description}")
            print()
        suggested = [f for f in fixes if f not in applied]
        if suggested and args.fmt == "text":
            print(f"Suggested fixes ({len(suggested)} — review before applying):")
            for fix in suggested:
                print(f"  ? [{fix.file_path}] {fix.description}")
            print()
    else:
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


def _run_fix(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    context = RepositoryContext(args.path)

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
        except ValueError as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        config = LinterConfig.default()

    linter = Linter(context, config)

    if not args.use_llm:
        violations, fixes = linter.fix()
        applied = linter.apply_fixes(fixes)
        if applied:
            print(f"Fixed {len(applied)} issue(s):")
            for fix in applied:
                print(f"  ✓ [{fix.file_path}] {fix.description}")
        else:
            print("No auto-fixable violations found.")
        suggested = [f for f in fixes if f not in applied]
        if suggested:
            print(f"\nSuggested fixes ({len(suggested)} — review before applying):")
            for fix in suggested:
                print(f"  ? [{fix.file_path}] {fix.description}")
        sys.exit(0)

    if args.model:
        config.llm.model = args.model
    if args.max_iterations:
        config.llm.max_iterations = args.max_iterations

    try:
        from .llm._litellm import LiteLLMProvider
    except ImportError:
        print(
            "Error: LLM features require litellm. Install with: pip install skillsaw[llm]",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
    )

    provider = LiteLLMProvider()

    violations = linter.run()
    llm_rules = {r.rule_id: r for r in linter.rules if r.llm_fix_prompt is not None}
    llm_violations = [
        v for v in violations if v.rule_id in llm_rules and v.severity != Severity.INFO
    ]

    print(f"Linting: {args.path}")
    print(f"Model: {config.llm.model}")
    print(f"Found {len(llm_violations)} LLM-fixable violation(s) across {len(llm_rules)} rule(s)\n")

    if not llm_violations:
        print("No LLM-fixable violations found.")
        sys.exit(0)

    def _progress(files_done, file_violations):
        path = file_violations[0].file_path if file_violations else None
        rel = path.relative_to(args.path) if path else "?"
        print(f"  ✎ Fixed {rel} ({len(file_violations)} violation(s))")

    result = linter.llm_fix(provider, callback=_progress)

    if not result.success:
        print("LLM fix did not improve violations — changes reverted.")
        sys.exit(1)

    if not result.files_modified:
        print("No LLM-fixable violations found.")
        sys.exit(0)

    print(
        f"Fixed {result.violations_fixed} of {result.violations_before} "
        f"LLM-fixable violations across {len(result.files_modified)} file(s)\n"
    )

    if result.diffs:
        print("── Changes " + "─" * 50 + "\n")
        for diff_text in result.diffs.values():
            print(diff_text)
        print()

    usage = result.total_usage
    total_tokens = usage.prompt_tokens + usage.completion_tokens
    print(
        f"Token usage: ~{total_tokens:,} tokens "
        f"(prompt: {usage.prompt_tokens:,} / completion: {usage.completion_tokens:,})"
    )

    if result.violations_after > 0:
        print(f"\n{result.violations_after} violation(s) remain.")

    print("Changes applied.")
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
