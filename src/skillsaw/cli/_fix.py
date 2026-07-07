"""Handler for the ``skillsaw fix`` subcommand."""

from __future__ import annotations

import difflib
import sys

from ..context import RepositoryContext
from ..linter import Linter
from ..rule import AutofixConfidence
from ._config import load_config
from ._helpers import (
    _RuleProgress,
    _ansi_colors,
    _resolve_lint_paths,
    color_enabled,
)


def _rel(path, root):
    """Repo-relative display path, matching lint output style."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _run_fix(args):
    missing = [p for p in args.path if not p.exists()]
    for p in missing:
        print(f"Error: Path not found: {p}", file=sys.stderr)
    if missing:
        sys.exit(1)

    paths = _resolve_lint_paths(args.path)

    config, _config_path = load_config(args, paths[0])

    rule_ids = set(args.rule_ids) if args.rule_ids else None
    skip_rule_ids = set(args.skip_rule_ids) if args.skip_rule_ids else None
    if rule_ids and skip_rule_ids:
        print("Error: --rule and --skip-rule cannot be combined", file=sys.stderr)
        sys.exit(1)

    dry_run = getattr(args, "dry_run", False)
    confidence = AutofixConfidence.SUGGEST if args.suggest else AutofixConfidence.SAFE

    applied = []
    suggested = []
    for fix_path in paths:
        context = RepositoryContext(
            fix_path,
            exclude_patterns=config.exclude_patterns,
            content_paths=config.content_paths,
        )
        try:
            linter = Linter(
                context,
                config,
                rule_ids=rule_ids,
                skip_rule_ids=skip_rule_ids,
                no_custom_rules=args.no_custom_rules,
                no_plugins=args.no_plugins,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        rule_progress = _RuleProgress(args)
        try:
            path_applied, path_suggested = linter.fix_and_apply(
                confidence, dry_run=dry_run, progress=rule_progress
            )
        finally:
            rule_progress.clear()

        if not dry_run and any(f.rule_id == "agentskill-name" for f in path_applied):
            context = RepositoryContext(
                fix_path,
                exclude_patterns=config.exclude_patterns,
                content_paths=config.content_paths,
            )
            linter = Linter(
                context,
                config,
                rule_ids=rule_ids,
                skip_rule_ids=skip_rule_ids,
                no_custom_rules=args.no_custom_rules,
                no_plugins=args.no_plugins,
            )
            rename_applied, rename_suggested = linter.fix_and_apply(confidence)
            path_applied.extend(rename_applied)
            path_suggested.extend(rename_suggested)

        applied.extend((f, context.root_path) for f in path_applied)
        suggested.extend((f, context.root_path) for f in path_suggested)

    c = _ansi_colors(color_enabled(sys.stdout, args.color))

    # Single-root runs print repo-relative paths, matching lint output.
    # Multi-root runs keep absolute paths — the same relative name in two
    # repos (e.g. CLAUDE.md) would be ambiguous.
    def _display(file_path, root):
        return _rel(file_path, root) if len(paths) == 1 else file_path

    if applied:
        label = "Would fix" if dry_run else "Fixed"
        print(f"{label} {len(applied)} issue(s):")
        for fix, root in applied:
            rel = _rel(fix.file_path, root)
            print(f"  {c['bold']}✓ [{_display(fix.file_path, root)}] {fix.description}{c['reset']}")
            if dry_run and fix.original_content != fix.fixed_content:
                diff_lines = difflib.unified_diff(
                    fix.original_content.splitlines(keepends=True),
                    fix.fixed_content.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
                for line in diff_lines:
                    line = line.rstrip("\n")
                    if line.startswith("+") and not line.startswith("+++"):
                        print(f"      {c['green']}{line}{c['reset']}")
                    elif line.startswith("-") and not line.startswith("---"):
                        print(f"      {c['red']}{line}{c['reset']}")
                    elif line.startswith("@@"):
                        print(f"      {c['cyan']}{line}{c['reset']}")
                    else:
                        print(f"      {line}")
                print(f"      {c['dim']}{'─' * 40}{c['reset']}")
    else:
        print("No auto-fixable violations found.")

    if suggested:
        print(f"\nSuggested fixes ({len(suggested)} — review before applying):")
        for fix, root in suggested:
            print(f"  ? [{_display(fix.file_path, root)}] {fix.description}")
        print("\nRun `skillsaw fix --suggest` to apply suggested fixes.")
        print("Run `skillsaw fix --suggest --dry-run` to preview changes.")

    if dry_run and applied:
        print(f"\n{c['yellow']}dry-run — no files were modified{c['reset']}")

    if applied and not dry_run:
        print("\nRun `skillsaw lint` to see remaining issues.")

    sys.exit(0)
