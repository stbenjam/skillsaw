"""Handler for the ``skillsaw context`` subcommand."""

from __future__ import annotations

import json
import sys

from ..context import RepositoryContext
from ._config import load_config
from ._helpers import _ansi_colors

_BAR_WIDTH = 20


def _bar(tokens: int, scale_max: int) -> str:
    if scale_max <= 0 or tokens <= 0:
        return ""
    return "█" * max(1, round(tokens / scale_max * _BAR_WIDTH))


def _status_suffix(item, colors) -> str:
    if item.status == "error":
        return f"  {colors['red']}✗ over error limit{colors['reset']}"
    if item.status == "warn":
        return f"  {colors['yellow']}⚠ over warn limit{colors['reset']}"
    return ""


def _print_rows(rows, colors) -> None:
    """rows: list of (tokens, label, item-or-None). Bars scale to the
    largest row in the section so relative weight is visible at a glance."""
    scale_max = max((tokens for tokens, _, _ in rows), default=0)
    for tokens, label, item in rows:
        bar = _bar(tokens, scale_max)
        suffix = _status_suffix(item, colors) if item is not None else ""
        print(
            f"  {tokens:>8,}  {colors['cyan']}{bar:<{_BAR_WIDTH}}{colors['reset']}"
            f"  {label}{suffix}"
        )


def _print_text(report, top: int) -> None:
    colors = _ansi_colors()
    bold, dim, reset = colors["bold"], colors["dim"], colors["reset"]

    print(f"{bold}Context budget for {report.root}{reset}")
    print(f"{dim}Token counts are estimates (chars/4); window: {report.window:,} tokens{reset}")
    print()

    if report.harness == "all":
        print(f"{bold}SESSION START{reset} {dim}— loaded into every session{reset}")
    else:
        print(
            f"{bold}SESSION START ({report.harness}){reset} "
            f"{dim}— loaded into every {report.harness} session{reset}"
        )
    rows = [
        (i.tokens, i.label if i.via is None else f"{i.label} {dim}(via {i.via}){reset}", i)
        for i in report.session_files
    ]
    for group in report.metadata:
        over = sum(1 for i in group.items if i.status in ("warn", "error"))
        label = f"{group.kind} descriptions ({len(group.items)})"
        if over:
            label += f" {colors['yellow']}⚠ {over} over limit{reset}"
        rows.append((group.total, label, None))
    if rows:
        _print_rows(rows, colors)
    else:
        print(f"  {dim}(none found){reset}")
    print(
        f"  {'─' * 8}\n"
        f"  {bold}{report.session_total:>8,}{reset}  total — "
        f"{report.window_percent:.2f}% of the {report.window:,}-token window"
    )
    if report.harness == "all" and len(report.by_harness) > 1:
        parts = [f"{h} {t:,}" for h, t in sorted(report.by_harness.items(), key=lambda kv: -kv[1])]
        print(
            f"  {dim}by harness (each session loads only its own files): "
            f"{' · '.join(parts)}{reset}"
        )
    print()

    shown = report.on_demand if top <= 0 else report.on_demand[:top]
    header = f"{bold}ON DEMAND{reset} {dim}— loaded when invoked or path-matched"
    if len(shown) < len(report.on_demand):
        header += f" (top {len(shown)} of {len(report.on_demand)}; --top 0 for all)"
    print(header + f"{reset}")
    if shown:
        _print_rows([(i.tokens, i.label, i) for i in shown], colors)
        print(
            f"  {'─' * 8}\n"
            f"  {bold}{report.on_demand_total:>8,}{reset}  total across "
            f"{len(report.on_demand)} files"
        )
    else:
        print(f"  {dim}(none found){reset}")

    over = report.over_limit()
    if over:
        errors = sum(1 for i in over if i.status == "error")
        warns = len(over) - errors
        parts = []
        if errors:
            parts.append(f"{colors['red']}{errors} over error limit{reset}")
        if warns:
            parts.append(f"{colors['yellow']}{warns} over warn limit{reset}")
        print(f"\n{', '.join(parts)} — enforced by the context-budget rule")


def _run_context(args):
    if not args.path.exists():
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)
    if args.window <= 0:
        print("Error: --window must be a positive token count", file=sys.stderr)
        sys.exit(1)

    config, _config_path = load_config(args, args.path)
    context = RepositoryContext(
        args.path,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    from ._tree import _apply_plugin_extensions

    _apply_plugin_extensions(context, config)

    from ..budget import compute_budget

    user_limits = config.get_rule_config("context-budget").get("limits") or {}
    report = compute_budget(
        context, user_limits=user_limits, window=args.window, harness=args.harness
    )

    if args.fmt == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_text(report, top=args.top)

    for message in context.plugin_extension_errors:
        print(f"Warning: {message}", file=sys.stderr)
    sys.exit(0)
