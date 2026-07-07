"""
Text output formatter — human-readable terminal output with optional ANSI colors.
"""

import os
from typing import List, Optional

from ..rule import AutofixConfidence, Rule, RuleViolation, Severity
from ..rule_docs import rule_doc_url
from . import get_counts, relative_path, should_show_info


def format_duration(seconds: float) -> str:
    """Human-friendly duration: 450ms, 2.3s, 1m 12s."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs}s"


def format_text(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
    baseline_suppressed: int = 0,
    duration: Optional[float] = None,
    grade=None,
    fail_level: str = "error",
) -> str:
    show_info = should_show_info(verbose, fail_level)
    no_color = "NO_COLOR" in os.environ
    red = "" if no_color else "\033[91m"
    yellow = "" if no_color else "\033[93m"
    blue = "" if no_color else "\033[94m"
    green = "" if no_color else "\033[92m"
    bold = "" if no_color else "\033[1m"
    reset = "" if no_color else "\033[0m"

    errors, warnings, info = get_counts(violations)

    errors_list = [v for v in violations if v.severity == Severity.ERROR]
    warnings_list = [v for v in violations if v.severity == Severity.WARNING]
    info_list = [v for v in violations if v.severity == Severity.INFO]

    def fix_marker(v: RuleViolation) -> str:
        """Ruff-style fixability marker: [*] safe, [?] needs --suggest."""
        if not v.fixable:
            return ""
        return " [*]" if v.fix_confidence == AutofixConfidence.SAFE else " [?]"

    def fmt_violation(v: RuleViolation) -> str:
        icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}[v.severity.value]
        rel = relative_path(v.file_path, context.root_path)
        location = ""
        if rel:
            location = f" [{rel}:{v.file_line}]" if v.file_line else f" [{rel}]"
        return (
            f"{icon} {v.severity.value.upper()} ({v.rule_id}){fix_marker(v)}{location}: {v.message}"
        )

    output = []

    if errors_list:
        output.append(f"\n{red}{bold}Errors:{reset}")
        for v in errors_list:
            output.append(f"  {fmt_violation(v)}")

    if warnings_list:
        output.append(f"\n{yellow}{bold}Warnings:{reset}")
        for v in warnings_list:
            output.append(f"  {fmt_violation(v)}")

    if show_info and info_list:
        output.append(f"\n{blue}{bold}Info:{reset}")
        for v in info_list:
            output.append(f"  {fmt_violation(v)}")

    shown = errors_list + warnings_list + (info_list if show_info else [])
    # Synthetic rule IDs (e.g. invalid-config) have no documentation page —
    # only link rules that actually ran as builtins.
    builtin_ids = {r.rule_id for r in rules if getattr(r, "_source", "builtin") == "builtin"}
    documented = sorted({v.rule_id for v in shown if v.rule_id in builtin_ids})
    if documented:
        output.append(f"\n{bold}Rule docs{reset} (or run `skillsaw explain <rule-id>`):")
        for rule_id in documented:
            output.append(f"  {rule_doc_url(rule_id)}")

    output.append(f"\n{bold}Scanned:{reset}")
    repo_types_str = ", ".join(context.repo_type_names(include_unknown=False))
    output.append(f"  Repo type: {repo_types_str or 'unknown'}")
    output.append(f"  Plugins:   {len(context.plugins)}")
    output.append(f"  Skills:    {len(context.skills)}")
    output.append(f"  Rules run: {len(rules)}")
    if duration is not None:
        output.append(f"  Took:      {format_duration(duration)}")

    output.append(f"\n{bold}Summary:{reset}")
    output.append(f"  {red}Errors:   {errors}{reset}")
    output.append(f"  {yellow}Warnings: {warnings}{reset}")
    if show_info:
        output.append(f"  {blue}Info:     {info}{reset}")
    if baseline_suppressed:
        dim = "" if no_color else "\033[2m"
        output.append(f"  {dim}Baseline: {baseline_suppressed} suppressed{reset}")
    if grade is not None:
        grade_color = {"A": green, "B": green, "C": yellow, "D": red, "F": red}[grade.letter[0]]
        output.append(
            f"  Grade:    {grade_color}{bold}{grade.letter}{reset} "
            f"({grade.density:.2f} weighted violations per 10k tokens)"
        )
        if grade.info and not show_info:
            dim = "" if no_color else "\033[2m"
            output.append(
                f"  {dim}{grade.info} info-level violation(s) count toward"
                f" the grade — run with -v to see them{reset}"
            )

    # Legend for the [*]/[?] markers and the lint-to-fix hint. Counts are
    # over the violations shown above, so marked lines and counts agree
    # (`skillsaw fix` groups per-file fixes and may report different totals).
    safe_fixable = sum(1 for v in shown if v.fixable and v.fix_confidence == AutofixConfidence.SAFE)
    suggest_fixable = sum(
        1 for v in shown if v.fixable and v.fix_confidence != AutofixConfidence.SAFE
    )
    if safe_fixable and suggest_fixable:
        output.append(
            f"  {green}[*] {safe_fixable} violation(s) fixable with `skillsaw fix`"
            f" ([?] {suggest_fixable} more with `skillsaw fix --suggest`){reset}"
        )
    elif safe_fixable:
        output.append(
            f"  {green}[*] {safe_fixable} violation(s) fixable with `skillsaw fix`{reset}"
        )
    elif suggest_fixable:
        output.append(
            f"  {green}[?] {suggest_fixable} violation(s) fixable with"
            f" `skillsaw fix --suggest`{reset}"
        )

    if errors == 0 and warnings == 0 and (fail_level != "info" or info == 0):
        output.append(f"\n{green}{bold}✓ All checks passed!{reset}")

    return "\n".join(output)
