"""Handler for the ``skillsaw baseline`` subcommand."""

from __future__ import annotations

import sys

from ..context import RepositoryContext
from ..linter import Linter
from ..rule import Severity
from ._config import _get_version, load_config


def _run_baseline(args):
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
        linter = Linter(context, config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    violations = [v for v in linter.run() if v.severity != Severity.INFO]

    from ..baseline import build_baseline, save_baseline, BASELINE_FILENAME

    cli_version = _get_version()
    baseline_modes = {r.rule_id: r.baseline_mode for r in linter.rules if r.baseline_mode}

    if config_path:
        output_path = config_path.parent / BASELINE_FILENAME
    else:
        output_path = args.path / BASELINE_FILENAME

    baseline = build_baseline(violations, output_path.resolve().parent, cli_version, baseline_modes)

    save_baseline(output_path, baseline)
    print(f"Baselined {len(baseline.violations)} violation(s) to {output_path}")
    sys.exit(0)
