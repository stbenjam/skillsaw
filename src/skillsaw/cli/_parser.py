"""Argparse tree for all skillsaw subcommands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import _FAIL_ON_LEVELS
from ..context import RepositoryType
from ..formatters import EXTENSION_MAP, FORMATS
from ._config import _get_version

_COLOR_HELP = (
    "Force ANSI colors and terminal hyperlinks on (--color) or off "
    "(--no-color). Default: color only when stdout is a terminal; "
    "FORCE_COLOR and NO_COLOR are also honored."
)


def _add_color_flag(subparser) -> None:
    subparser.add_argument(
        "--color",
        action=argparse.BooleanOptionalAction,
        default=None,
        dest="color",
        help=_COLOR_HELP,
    )


_NO_NETWORK_HELP = (
    "Skip every rule that makes outbound network requests, whatever the "
    "linted repository's .skillsaw.yaml enables (env: SKILLSAW_NO_NETWORK=1)"
)


_ALLOW_PRIVATE_HOSTS_HELP = (
    "Let network rules probe loopback, private and link-local hosts. Off "
    "unless the operator asks: the linted repository cannot enable it "
    "(env: SKILLSAW_ALLOW_PRIVATE_HOSTS=1)"
)


# ``fix`` accepts both flags so that one argv works across subcommands,
# but it never goes on the network whatever they say — it forces the gate
# on itself, because the autofix loop would re-probe every URL once per
# pass and discard the results. So --no-network is redundant there and
# --allow-private-hosts does nothing at all, and the help says so rather
# than letting the reference page describe a control that is not one.
_FIX_NETWORK_NOTE = (
    ". Accepted on fix for argv compatibility only: fix never runs "
    "network rules, so this has no effect there"
)


def _add_network_flags(subparser, note: str = "") -> None:
    """The operator's network controls, on every rule-executing subcommand.

    Shared rather than repeated per subparser, so a subcommand cannot be
    added without them.
    """
    subparser.add_argument(
        "--no-network",
        action="store_true",
        dest="no_network",
        help=_NO_NETWORK_HELP + note,
    )
    subparser.add_argument(
        "--allow-private-hosts",
        action="store_true",
        dest="allow_private_hosts",
        help=_ALLOW_PRIVATE_HOSTS_HELP + note,
    )


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
        help="Treat warnings as errors (equivalent to --fail-on warning; "
        "overrides the config file's strict/fail-on settings)",
    )
    lint_parser.add_argument(
        "--fail-on",
        dest="fail_on",
        choices=list(_FAIL_ON_LEVELS),
        default=None,
        help="Fail on violations at this severity or above (default: error; "
        "--strict is equivalent to --fail-on warning). Overrides the config "
        "file's strict/fail-on settings.",
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
    _add_network_flags(lint_parser)
    lint_parser.add_argument(
        "--no-plugins",
        action="store_true",
        dest="no_plugins",
        help="Skip rules from installed plugin packages (skillsaw.plugins entry points)",
    )
    lint_parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable the interactive per-rule progress indicator "
        "(auto-disabled when stderr is not a terminal)",
    )
    _add_color_flag(lint_parser)

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
    _add_network_flags(fix_parser, note=_FIX_NETWORK_NOTE)
    fix_parser.add_argument(
        "--no-plugins",
        action="store_true",
        dest="no_plugins",
        help="Skip rules from installed plugin packages (skillsaw.plugins entry points)",
    )
    fix_parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable the interactive per-rule progress indicator "
        "(auto-disabled when stderr is not a terminal)",
    )
    _add_color_flag(fix_parser)

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

    # --- feedback ---
    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Create a local diagnostic bundle for a bug report",
        description=(
            "Create a local, reviewable diagnostic bundle for a skillsaw bug report. "
            "It never uploads data, and includes no repository files unless --include or "
            "--config names them. Named files are copied verbatim: skillsaw does not scan "
            "them for secrets, so review the ZIP before sharing it. Two things are refused "
            "outright: files whose name means credentials (.env, id_rsa, *.pem, ...), and "
            "files already excluded by .gitignore, .dockerignore, .npmignore, .helmignore "
            "or .gcloudignore."
        ),
    )
    feedback_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Repository to diagnose (default: current directory)",
    )
    feedback_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file to copy into the bundle verbatim (default: auto-discover only; review it for secrets yourself)",
    )
    feedback_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Bundle ZIP path (default: .skillsaw-feedback/ under the repository)",
    )
    feedback_parser.add_argument(
        "--message",
        default="",
        help="Short description of the problem to include in the bundle",
    )
    feedback_parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATH",
        help="Copy a repository-relative UTF-8 text file into the bundle verbatim (repeatable; review it for secrets yourself)",
    )
    feedback_parser.add_argument(
        "--with-extensions",
        action="store_true",
        help="Run custom and installed plugin rules in the diagnostic lint run",
    )
    feedback_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the bundle result as JSON for agents and automation",
    )

    # --- list-rules ---
    subparsers.add_parser("list-rules", help="List all available builtin and plugin rules")

    # --- plugins ---
    subparsers.add_parser(
        "plugins",
        help="List installed rule plugins and the rules they provide",
        description="List rule plugins installed as Python packages "
        "(skillsaw.plugins entry points), the rules each provides, and any "
        "plugins that failed to load.",
    )

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
    _add_color_flag(explain_parser)

    # --- docs ---
    docs_parser = subparsers.add_parser(
        "docs",
        help="Generate documentation for a Claude or Codex plugin, marketplace, or .claude repository",
        description="Generate documentation for a Claude or Codex plugin, marketplace, or .claude repository",
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

    # --- port ---
    port_parser = subparsers.add_parser(
        "port",
        help="Port Claude Code and Codex plugins to Agent Plugins v1 packages",
    )
    port_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Plugin, marketplace, or repository to port (default: current directory)",
    )
    port_parser.add_argument(
        "--to",
        dest="target",
        default="agent-plugin",
        metavar="FORMAT",
        help="Target format (default and currently only: agent-plugin)",
    )
    port_parser.add_argument(
        "-c",
        "--config",
        type=Path,
        help="Path to .skillsaw.yaml config file (default: auto-discover from the path)",
    )
    port_parser.add_argument(
        "--marketplaces",
        default="codex",
        metavar="FORMATS",
        help="Comma-separated marketplace catalogs to generate for the ported "
        "plugins so catalog-driven clients can discover them "
        "(default: codex; use 'none' to skip)",
    )
    port_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show the files that would be written without writing them",
    )
    port_parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="Disable the interactive conversion progress indicator "
        "(auto-disabled when stderr is not a terminal)",
    )
    _add_color_flag(port_parser)

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
    baseline_parser.add_argument(
        "--no-custom-rules",
        action="store_true",
        dest="no_custom_rules",
        help="Skip custom rules defined in .skillsaw.yaml (recommended for untrusted repositories)",
    )
    _add_network_flags(baseline_parser)
    baseline_parser.add_argument(
        "--no-plugins",
        action="store_true",
        dest="no_plugins",
        help="Skip rules from installed plugin packages (skillsaw.plugins entry points)",
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
    badge_parser.add_argument(
        "--large",
        action="store_true",
        help="Also render a self-contained SVG report card (.skillsaw-card.svg) "
        "next to the badge JSON",
    )
    badge_parser.add_argument(
        "--theme",
        choices=["light", "dark"],
        default="dark",
        help="Report card color theme, used with --large (default: dark)",
    )
    badge_parser.add_argument(
        "--no-custom-rules",
        action="store_true",
        dest="no_custom_rules",
        help="Skip custom rules defined in .skillsaw.yaml (recommended for untrusted repositories)",
    )
    _add_network_flags(badge_parser)
    badge_parser.add_argument(
        "--no-plugins",
        action="store_true",
        dest="no_plugins",
        help="Skip rules from installed plugin packages (skillsaw.plugins entry points)",
    )
    _add_color_flag(badge_parser)

    # --- add ---
    subparsers.add_parser(
        "add",
        help="Scaffold marketplaces, plugins, skills, commands, agents, and hooks",
        add_help=False,
    )

    return parser
