"""Argparse tree for all skillsaw subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..context import RepositoryType
from ..formatters import EXTENSION_MAP, FORMATS
from ._config import _get_version


def _build_parser():
    """Build the main argument parser with all subcommands.

    Extracted so that documentation generators can introspect the real parser
    without running main().
    """
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
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="Paths to skill, plugin, or marketplace directories/files (default: current directory)",
    )
    lint_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover from the first path)",
    )
    lint_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show info-level messages"
    )
    lint_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit with error code if warnings exist)",
    )
    # Deprecated: use `skillsaw fix` instead. Hidden from --help.
    lint_parser.add_argument("--fix", action="store_true", help=argparse.SUPPRESS)
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
        metavar="[FORMAT:]FILE",
        help="Write output to FILE. Format is inferred from extension "
        f"({', '.join(sorted(EXTENSION_MAP))}) "
        "or set explicitly with a FORMAT: prefix (e.g. gitlab:report.json). "
        "Use the prefix when an extension is ambiguous (e.g. .json could be "
        "json or gitlab/code-climate). Can be specified multiple times.",
    )
    lint_parser.add_argument(
        "--type",
        dest="repo_types",
        action="append",
        default=[],
        metavar="TYPE",
        help="Override auto-detected repository type (repeatable). "
        "Values: "
        + ", ".join(t.value for t in RepositoryType if t is not RepositoryType.UNKNOWN)
        + ".",
    )
    lint_parser.add_argument(
        "--rule",
        dest="rule_ids",
        action="append",
        default=[],
        metavar="RULE",
        help="Only run these rules (repeatable). Config still comes from .skillsaw.yaml.",
    )
    lint_parser.add_argument(
        "--skip-rule",
        dest="skip_rule_ids",
        action="append",
        default=[],
        metavar="RULE",
        help="Skip these rules (repeatable). Cannot be combined with --rule.",
    )
    lint_parser.add_argument(
        "--no-baseline",
        action="store_true",
        dest="no_baseline",
        help="Ignore baseline file even if .skillsaw-baseline.json exists",
    )
    lint_parser.add_argument(
        "--no-custom-rules",
        action="store_true",
        dest="no_custom_rules",
        help="Skip custom rules defined in .skillsaw.yaml (recommended for CI on untrusted PRs)",
    )
    lint_parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable the interactive per-rule progress indicator "
        "(auto-disabled when stderr is not a terminal)",
    )

    # --- fix ---
    fix_parser = subparsers.add_parser(
        "fix",
        help="Automatically fix lint violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fix_parser.add_argument(
        "path",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="Paths to repositories or files (default: current directory)",
    )
    fix_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover from the first path)",
    )
    fix_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview fixes without writing changes",
    )
    fix_parser.add_argument(
        "--suggest",
        action="store_true",
        help="Also apply suggested fixes (not just safe ones)",
    )
    fix_parser.add_argument(
        "--rule",
        dest="rule_ids",
        action="append",
        default=[],
        metavar="RULE",
        help="Only run these rules (repeatable). Config still comes from .skillsaw.yaml.",
    )
    fix_parser.add_argument(
        "--skip-rule",
        dest="skip_rule_ids",
        action="append",
        default=[],
        metavar="RULE",
        help="Skip these rules (repeatable). Cannot be combined with --rule.",
    )
    fix_parser.add_argument(
        "--no-custom-rules",
        action="store_true",
        dest="no_custom_rules",
        help="Skip custom rules defined in .skillsaw.yaml (recommended for CI on untrusted PRs)",
    )
    fix_parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable the interactive per-rule progress indicator "
        "(auto-disabled when stderr is not a terminal)",
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

    # --- explain ---
    explain_parser = subparsers.add_parser(
        "explain",
        help="Show documentation and effective configuration for a rule",
    )
    explain_parser.add_argument(
        "rule_id",
        metavar="RULE",
        help="Rule ID to explain (e.g. content-weak-language)",
    )
    explain_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Repository to compute effective config in (default: current directory)",
    )
    explain_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover)",
    )

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
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover)",
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
    docs_parser.add_argument(
        "--theme",
        default=None,
        help="Color theme for HTML output. Presets: indigo (default), forest-green, "
        "ocean-blue, sunset-orange, royal-purple, crimson-red.",
    )

    # --- tree ---
    tree_parser = subparsers.add_parser(
        "tree",
        help="Display the repository lint tree",
    )
    tree_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to repository (default: current directory)",
    )
    tree_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file",
    )
    tree_parser.add_argument(
        "--format",
        dest="fmt",
        default="text",
        choices=["text", "dot"],
        help="Output format (default: text)",
    )

    # --- baseline ---
    baseline_parser = subparsers.add_parser(
        "baseline",
        help="Generate or update the baseline file from current violations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    baseline_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to repository (default: current directory)",
    )
    baseline_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file",
    )
    # --- badge ---
    badge_parser = subparsers.add_parser(
        "badge",
        help="Grade the repository and write a shields.io badge JSON file",
        description="Lint the repository, compute its letter grade, write a "
        "shields.io-compatible badge file, and print the markdown to embed it. "
        "Ignores any baseline so the published grade reflects all violations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    badge_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Path to repository (default: current directory)",
    )
    badge_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover)",
    )
    badge_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Badge JSON output path (default: .skillsaw-badge.json in the repository root)",
    )

    # --- add ---
    subparsers.add_parser(
        "add",
        help="Scaffold marketplaces, plugins, skills, commands, agents, and hooks",
        add_help=False,
    )

    return parser
