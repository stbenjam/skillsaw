"""Handler for the ``skillsaw baseline`` subcommand."""

from __future__ import annotations

import sys

from ..context import RepositoryContext
from ..linter import Linter
from ..rule import Severity
from ._config import _get_version, load_config
from skillsaw.paths import safe_resolve


def _run_baseline(args):
    """Create a baseline for the repository selected by CLI arguments."""
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config, config_path = load_config(args, args.path)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )

    try:
        linter = Linter(
            context,
            config,
            no_custom_rules=args.no_custom_rules,
            no_plugins=args.no_plugins,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    violations = [v for v in linter.run() if v.severity != Severity.INFO]
    if context.lint_tree_errors:
        for message in context.lint_tree_errors:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    from ..baseline import build_baseline, save_baseline, BASELINE_FILENAME

    cli_version = _get_version()
    baseline_modes = {r.rule_id: r.baseline_mode for r in linter.rules if r.baseline_mode}

    if config_path:
        output_path = config_path.parent / BASELINE_FILENAME
    else:
        output_path = args.path / BASELINE_FILENAME

    output_parent = safe_resolve(output_path.parent)
    if output_parent is None:
        print(
            f"Error: Could not resolve baseline output directory: {output_path.parent}",
            file=sys.stderr,
        )
        sys.exit(1)
    write_path = output_parent / output_path.name

    baseline = build_baseline(violations, output_parent, cli_version, baseline_modes)

    try:
        save_baseline(write_path, baseline)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Baselined {len(baseline.violations)} violation(s) to {output_path}")
    sys.exit(0)
