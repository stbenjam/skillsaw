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


def main():
    parser = argparse.ArgumentParser(
        description="Lint agent skills, plugins, and AI coding assistant context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Lint current directory
  skillsaw

  # Lint specific directory
  skillsaw /path/to/skills

  # Use custom config
  skillsaw --config .skillsaw.yaml

  # Verbose output
  skillsaw -v

  # Strict mode (warnings as errors)
  skillsaw --strict

  # JSON output to stdout
  skillsaw --format json

  # Text to stdout, SARIF + HTML to files
  skillsaw --output results.sarif --output report.html

  # Generate default config
  skillsaw --init

For more information, visit: https://github.com/stbenjam/skillsaw
        """,
    )

    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to skill, plugin, or marketplace directory (default: current directory)",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover)",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Show info-level messages")

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit with error code if warnings exist)",
    )

    parser.add_argument(
        "--format",
        dest="fmt",
        default="text",
        choices=FORMATS,
        help="Output format for stdout (default: text)",
    )

    parser.add_argument(
        "--output",
        dest="outputs",
        action="append",
        default=[],
        metavar="FILE",
        help="Write output to FILE (format inferred from extension: .json, .sarif, .html). "
        "Can be specified multiple times.",
    )

    parser.add_argument(
        "--init", action="store_true", help="Generate a default .skillsaw.yaml config file"
    )

    parser.add_argument(
        "--list-rules", action="store_true", help="List all available builtin rules"
    )

    # Get version from package metadata, fall back to __version__
    try:
        cli_version = version("skillsaw")
    except PackageNotFoundError:
        cli_version = __version__

    parser.add_argument("--version", action="version", version=f"%(prog)s {cli_version}")

    args = parser.parse_args()

    # Handle --init
    if args.init:
        config_path = args.path / ".skillsaw.yaml"
        if config_path.exists():
            print(f"Config file already exists: {config_path}")
            sys.exit(1)

        config = LinterConfig.default()
        config.save(config_path)
        print(f"Created default config: {config_path}")
        sys.exit(0)

    # Handle --list-rules
    if args.list_rules:
        from skillsaw.rules.builtin import BUILTIN_RULES

        print("Available builtin rules:\n")
        for rule_class in BUILTIN_RULES:
            rule = rule_class()
            print(f"  {rule.rule_id}")
            print(f"    {rule.description}")
            print(f"    Default severity: {rule.default_severity().value}")
            print()
        sys.exit(0)

    # Validate --output extensions early
    output_formats = {}
    for output_path in args.outputs:
        try:
            output_formats[output_path] = infer_format(output_path)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Validate path
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # Create repository context
    if args.fmt == "text":
        print(f"Linting: {args.path}\n")
    context = RepositoryContext(args.path)

    # Show repository type
    if context.repo_type == RepositoryType.UNKNOWN:
        print("Warning: Directory doesn't appear to be a recognized repository", file=sys.stderr)
        print(
            "Expected: .claude-plugin/plugin.json, plugins/ directory, or SKILL.md (agentskills.io)\n",
            file=sys.stderr,
        )

    # Load config
    if args.config:
        config_path = args.config
        if not config_path.exists():
            print(f"Error: Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        # Auto-discover config
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

    # Apply strict mode from CLI
    if args.strict:
        config.strict = True

    # Create and run linter
    linter = Linter(context, config)
    violations = linter.run()

    # Format and print to stdout
    stdout_output = format_report(
        args.fmt, violations, context, linter.rules, cli_version, verbose=args.verbose
    )
    print(stdout_output)

    # Write to output files
    for output_path, fmt in output_formats.items():
        file_output = format_report(
            fmt, violations, context, linter.rules, cli_version, verbose=args.verbose
        )
        Path(output_path).write_text(file_output, encoding="utf-8")

    # Exit with appropriate code
    errors, warnings_count, info = get_counts(violations)

    if errors > 0:
        sys.exit(1)
    elif config.strict and warnings_count > 0:
        sys.exit(1)
    else:
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
