"""Handler for the ``skillsaw fix`` subcommand."""

from __future__ import annotations

import shutil
import sys
import time

from ..context import RepositoryContext
from ..linter import Linter
from ..rule import AutofixConfidence, Severity
from ._config import load_config
from ._helpers import (
    _RuleProgress,
    _ansi_colors,
    _apply_llm_patch,
    _print_colored_diff,
    _print_token_usage,
    _require_llm_provider,
    _resolve_lint_paths,
    _resolve_patch_path,
    _save_llm_patch,
)


def _run_fix(args):
    missing = [p for p in args.path if not p.exists()]
    for p in missing:
        print(f"Error: Path not found: {p}", file=sys.stderr)
    if missing:
        sys.exit(1)

    paths = _resolve_lint_paths(args.path)

    if getattr(args, "apply_patch", False):
        if len(paths) > 1:
            print("Error: --apply-patch accepts a single path", file=sys.stderr)
            sys.exit(1)
        root_path = paths[0]
        patch_path = _resolve_patch_path(args, root_path)
        _apply_llm_patch(patch_path, root_path)
        sys.exit(0)

    config, _config_path = load_config(args, paths[0])

    rule_ids = set(args.rule_ids) if args.rule_ids else None
    skip_rule_ids = set(args.skip_rule_ids) if args.skip_rule_ids else None
    if rule_ids and skip_rule_ids:
        print("Error: --rule and --skip-rule cannot be combined", file=sys.stderr)
        sys.exit(1)

    if not args.use_llm:
        import difflib

        dry_run = getattr(args, "dry_run", False)
        confidence = AutofixConfidence.SUGGEST if args.suggest else AutofixConfidence.SAFE

        applied = []
        suggested = []
        for fix_path in paths:
            context = RepositoryContext(fix_path)
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
                context = RepositoryContext(fix_path)
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
            suggested.extend(path_suggested)

        c = _ansi_colors()

        if applied:
            label = "Would fix" if dry_run else "Fixed"
            print(f"{label} {len(applied)} issue(s):")
            for fix, root in applied:
                print(f"  {c['bold']}✓ [{fix.file_path}] {fix.description}{c['reset']}")
                if dry_run and fix.original_content != fix.fixed_content:
                    try:
                        rel = fix.file_path.relative_to(root)
                    except ValueError:
                        rel = fix.file_path
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
            for fix in suggested:
                print(f"  ? [{fix.file_path}] {fix.description}")
            print("\nRun `skillsaw fix --suggest` to apply suggested fixes.")
            print("Run `skillsaw fix --suggest --dry-run` to preview changes.")

        if dry_run and applied:
            print(f"\n{c['yellow']}dry-run — no files were modified{c['reset']}")

        sys.exit(0)

    # LLM fix runs an interactive session against one repository
    if len(paths) > 1:
        print("Error: --llm accepts a single path", file=sys.stderr)
        sys.exit(1)

    context = RepositoryContext(paths[0])
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

    if args.model:
        config.llm.model = args.model
    if args.max_iterations is not None:
        if args.max_iterations < 1:
            print(
                f"Error: --max-iterations must be >= 1, got {args.max_iterations}",
                file=sys.stderr,
            )
            sys.exit(1)
        config.llm.max_iterations = args.max_iterations

    c = _ansi_colors()
    provider = _require_llm_provider(config)

    is_tty = sys.stdout.isatty()
    term_size = shutil.get_terminal_size((80, 24))
    term_width = term_size.columns
    term_rows = term_size.lines

    violations = linter.run()
    llm_rules = {r.rule_id: r for r in linter.rules if r.llm_fix_prompt is not None}
    min_severity = Severity.INFO if args.all else Severity.WARNING
    llm_violations = [
        v
        for v in violations
        if v.rule_id in llm_rules
        and Linter._SEVERITY_ORDER.get(v.severity, 99) <= Linter._SEVERITY_ORDER[min_severity]
    ]

    files_with_violations = set()
    for v in llm_violations:
        if v.file_path:
            files_with_violations.add(v.file_path.resolve())

    print(f"\n{c['bold']}skillsaw fix{c['reset']} {c['dim']}({config.llm.model}){c['reset']}")
    print(f"{len(llm_violations)} violation(s) across " f"{len(files_with_violations)} file(s)\n")

    if not llm_violations:
        print(f"{c['green']}No fixable violations found.{c['reset']}")
        sys.exit(0)

    def _progress_bar(current, total, width=20):
        filled = int(width * current / total) if total else 0
        bar = "█" * filled + "░" * (width - filled)
        return f"{c['dim']}[{c['reset']}{c['cyan']}{bar}{c['reset']}{c['dim']}]{c['reset']}"

    def _setup_scroll_region():
        if not is_tty or c["no_color"]:
            return
        sys.stdout.write(f"\033[1;{term_rows - 1}r")
        sys.stdout.write(f"\033[2J")
        sys.stdout.write(f"\033[1;1H")
        sys.stdout.flush()

    def _update_status_bar(text):
        if not is_tty or c["no_color"]:
            return
        padded = text[:term_width].ljust(term_width)
        sys.stdout.write(f"\033[s\033[{term_rows};1H\033[2K{padded}\033[u")
        sys.stdout.flush()

    def _teardown_scroll_region():
        if not is_tty or c["no_color"]:
            return
        sys.stdout.write(f"\033[1;{term_rows}r")
        sys.stdout.write(f"\033[{term_rows};1H\033[2K")
        sys.stdout.flush()

    def _on_event(event_type, **kw):
        if event_type == "file_start":
            print(
                f"{c['bold']}{kw['rel_path']}{c['reset']}"
                f"  {c['dim']}{kw['num_violations']} violation(s):"
                f" {', '.join(kw['rule_ids'])}{c['reset']}"
            )
        elif event_type == "iteration":
            tag = f"{c['dim']}[{kw['rel_path']}]{c['reset']} "
            print(
                f"  {tag}{c['dim']}iteration"
                f" {kw['iteration']}/{kw['max_iterations']}{c['reset']}"
            )
        elif event_type == "tool_call":
            tool_args = kw.get("arguments", {})
            arg_summary = ""
            if "path" in tool_args:
                arg_summary = str(tool_args["path"])
            elif tool_args:
                first_key = next(iter(tool_args))
                val = str(tool_args[first_key])
                if len(val) > 40:
                    val = val[:37] + "..."
                arg_summary = val
            tag = f"{c['dim']}[{kw['rel_path']}]{c['reset']} "
            print(f"  {tag}{kw['name']}({arg_summary})")
        elif event_type == "retry":
            tag = f"{c['dim']}[{kw['rel_path']}]{c['reset']} "
            print(
                f"  {tag}{c['yellow']}{kw['remaining']} violation(s)"
                f" remain, retrying...{c['reset']}"
            )
        elif event_type == "file_done":
            remaining = kw.get("remaining", 0)
            changed = kw.get("changed", False)
            tag = f"{c['dim']}[{kw['rel_path']}]{c['reset']} "
            if not changed:
                print(f"  {tag}{c['yellow']}no changes{c['reset']}")
            elif remaining == 0:
                print(
                    f"  {tag}{c['green']}✓ all {kw['num_violations']}"
                    f" violation(s) fixed{c['reset']}"
                )
            else:
                fixed = kw["num_violations"] - remaining
                print(f"  {tag}{c['red']}{fixed} fixed," f" {remaining} failed{c['reset']}")
            print()

    max_workers = args.workers or config.llm.max_workers

    start_time = time.monotonic()

    def _on_event_with_timer(event_type, **kw):
        if event_type == "progress":
            elapsed = time.monotonic() - start_time
            elapsed_str = f"{int(elapsed)}s"
            eta_str = ""
            if 0 < kw["completed"] < kw["file_count"]:
                rate = elapsed / kw["completed"]
                remaining = rate * (kw["file_count"] - kw["completed"])
                eta_str = f" ETA {int(remaining)}s"
            bar = _progress_bar(kw["completed"], kw["file_count"])
            status = f" {kw['completed']}/{kw['file_count']} files {elapsed_str}{eta_str}"
            _update_status_bar(f" {bar}{status}")
            return
        _on_event(event_type, **kw)

    dry_run = getattr(args, "dry_run", False)

    _setup_scroll_region()
    try:
        result = linter.llm_fix(
            provider,
            callback=_on_event_with_timer,
            min_severity=min_severity,
            max_workers=max_workers,
            dry_run=dry_run,
        )
    finally:
        _teardown_scroll_region()

    if not result.success:
        if dry_run:
            print(f"\n{c['yellow']}LLM fix would not improve violations.{c['reset']}")
            sys.exit(0)
        print(f"\n{c['red']}LLM fix did not improve violations" f" — changes reverted.{c['reset']}")
        sys.exit(1)

    if not result.diffs and not result.files_modified:
        print(f"{c['green']}No fixable violations found.{c['reset']}")
        sys.exit(0)

    label = "Dry-run results" if dry_run else "Results"
    print(f"\n{c['bold']}{label}{c['reset']}")
    print(
        f"  {c['green']}{result.violations_fixed} fixed{c['reset']}"
        f" {c['dim']}of {result.violations_before}{c['reset']}"
    )
    if result.violations_after > 0:
        print(f"  {c['yellow']}{result.violations_after} remaining{c['reset']}")
    if dry_run:
        print(f"  {c['yellow']}dry-run — no files were modified{c['reset']}")
        if result.diffs:
            patch_path = _resolve_patch_path(args, context.root_path)
            _save_llm_patch(result.diffs, patch_path)
            print(f"  {c['cyan']}Patch saved to {patch_path}{c['reset']}")
            print(f"\n  {c['bold']}To apply:{c['reset']}" f" skillsaw fix --apply-patch")
    else:
        print(f"  {len(result.files_modified)} file(s) modified")

    _print_token_usage(result.total_usage, c, indent="  ")
    _print_colored_diff(result.diffs, c, header="Changes", separator=True)

    sys.exit(0)
