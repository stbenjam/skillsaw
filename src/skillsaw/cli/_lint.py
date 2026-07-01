"""Handler for the ``skillsaw lint`` subcommand."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from ..context import RepositoryContext, RepositoryType
from ..formatters import format_report, get_counts, parse_output_spec
from ..linter import Linter
from ._config import _get_version, load_config
from ._helpers import (
    _RuleProgress,
    _build_merged_context,
    _dedup_rules,
    _resolve_lint_paths,
)


def _run_lint(args):
    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(name)s: %(message)s",
            stream=sys.stderr,
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format="%(name)s: %(message)s",
            stream=sys.stderr,
        )

    cli_version = _get_version()

    output_formats = {}
    for spec in args.outputs:
        try:
            fmt, filepath = parse_output_spec(spec)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        resolved_path = Path(filepath).resolve()
        if resolved_path in output_formats and output_formats[resolved_path] != fmt:
            print(
                f"Error: --output targets '{filepath}' with conflicting formats "
                f"'{output_formats[resolved_path]}' and '{fmt}'",
                file=sys.stderr,
            )
            sys.exit(1)
        output_formats[resolved_path] = fmt

    missing_count = 0
    valid_raw_paths = []
    for p in args.path:
        if not p.exists():
            print(f"Error: Path not found: {p}", file=sys.stderr)
            missing_count += 1
        else:
            valid_raw_paths.append(p)

    if missing_count:
        print(f"{missing_count} path(s) not found", file=sys.stderr)

    if not valid_raw_paths:
        sys.exit(1)

    paths = _resolve_lint_paths(valid_raw_paths)

    if args.fmt == "text":
        print(f"skillsaw {cli_version}")
        print(f"Linting: {', '.join(str(p) for p in paths)}\n")

    override_types = None
    if args.repo_types:
        type_map = {t.value: t for t in RepositoryType if t is not RepositoryType.UNKNOWN}
        override_types = set()
        for val in args.repo_types:
            if val not in type_map:
                print(
                    f"Error: Unknown repository type '{val}'. "
                    f"Valid types: {', '.join(sorted(type_map.keys()))}",
                    file=sys.stderr,
                )
                sys.exit(1)
            override_types.add(type_map[val])

    config, config_path = load_config(args, paths[0])

    if config_path and args.verbose and args.fmt == "text":
        print(f"Using config: {config_path}\n")

    if args.strict:
        config.strict = True

    baseline = None
    if not args.no_baseline:
        from ..baseline import find_baseline, load_baseline

        baseline_path = find_baseline(config.config_dir or paths[0])

        if baseline_path:
            try:
                baseline = load_baseline(baseline_path)
                if args.verbose and args.fmt == "text":
                    print(
                        f"Using baseline: {baseline_path}"
                        f" ({len(baseline.violations)} entries)\n"
                    )
            except (ValueError, OSError) as e:
                print(f"Warning: Failed to load baseline: {e}", file=sys.stderr)

    rule_ids = set(args.rule_ids) if args.rule_ids else None
    skip_rule_ids = set(args.skip_rule_ids) if args.skip_rule_ids else None
    if rule_ids and skip_rule_ids:
        print("Error: --rule and --skip-rule cannot be combined", file=sys.stderr)
        sys.exit(1)

    lint_started = time.perf_counter()
    all_violations = []
    all_rules = []
    contexts = []
    baseline_suppressed = 0
    for lint_path in paths:
        context = RepositoryContext(lint_path, repo_types=override_types)
        contexts.append(context)

        if context.repo_type == RepositoryType.UNKNOWN:
            print(
                "Warning: Directory doesn't appear to be a recognized repository",
                file=sys.stderr,
            )
            print(
                "Expected: .claude-plugin/plugin.json, plugins/ directory,"
                " or SKILL.md (agentskills.io)\n",
                file=sys.stderr,
            )

        try:
            linter = Linter(
                context,
                config,
                rule_ids=rule_ids,
                skip_rule_ids=skip_rule_ids,
                baseline=baseline,
                no_custom_rules=args.no_custom_rules,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if args.fix:
            import warnings

            msg = (
                "`skillsaw lint --fix` is deprecated and will be removed in 1.0. "
                "Use `skillsaw fix` instead."
            )
            warnings.warn(msg, DeprecationWarning, stacklevel=1)
            print(f"Warning: {msg}", file=sys.stderr)
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
            rule_progress = _RuleProgress(args)
            try:
                violations = linter.run(progress=rule_progress)
            finally:
                rule_progress.clear()

        all_violations.extend(violations)
        all_rules.extend(linter.rules)
        baseline_suppressed += linter.baseline_suppressed_count

        if baseline and args.fmt == "text":
            stale = linter.stale_baseline_entries
            if stale:
                print(
                    f"Baseline: {len(stale)} stale"
                    f" {'entry' if len(stale) == 1 else 'entries'}"
                    f" (violations resolved since baseline was set)"
                )
                if args.verbose:
                    for entry in stale:
                        location = f" [{entry.file_path}]" if entry.file_path else ""
                        print(f"  - {entry.rule_id}{location}: {entry.message}")
                print("  Run `skillsaw baseline` to update.\n")

    merged_context = _build_merged_context(contexts)
    unique_rules = _dedup_rules(all_rules)
    lint_duration = time.perf_counter() - lint_started

    from ..grade import compute_grade

    content_tokens = sum(
        block.estimate_tokens() for ctx in contexts for block in ctx.lint_tree.content_blocks()
    )
    grade = compute_grade(all_violations, content_tokens)

    stdout_output = format_report(
        args.fmt,
        all_violations,
        merged_context,
        unique_rules,
        cli_version,
        verbose=args.verbose,
        baseline_suppressed=baseline_suppressed,
        duration=lint_duration,
        grade=grade,
    )
    print(stdout_output)

    report_cache = {}
    for output_path, fmt in output_formats.items():
        if fmt not in report_cache:
            report_cache[fmt] = format_report(
                fmt,
                all_violations,
                merged_context,
                unique_rules,
                cli_version,
                verbose=args.verbose,
                baseline_suppressed=baseline_suppressed,
                duration=lint_duration,
                grade=grade,
            )
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_cache[fmt], encoding="utf-8")

    errors, warnings_count, info = get_counts(all_violations)

    if missing_count > 0 or errors > 0:
        sys.exit(1)
    elif config.strict and warnings_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)
