"""
Entry point for skillsaw (and claudelint backward-compat shim)
"""

import argparse
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

from .context import RepositoryContext, RepositoryType
from .config import LinterConfig, find_config
from .linter import ClaudeLinter
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

    # Validate path
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    # Create repository context
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
            if args.verbose:
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
    linter = ClaudeLinter(context, config)
    violations = linter.run()

    # Format and print results
    output = linter.format_results(violations, verbose=args.verbose)
    print(output)

    # Exit with appropriate code
    errors, warnings_count, info = linter.get_counts(violations)

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
