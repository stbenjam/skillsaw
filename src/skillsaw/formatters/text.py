"""
Text output formatter — human-readable terminal output with optional ANSI colors.
"""

from pathlib import Path
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


def _osc8(url: str, text: str) -> str:
    """Wrap text in an OSC 8 terminal hyperlink."""
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def _file_uri(file_path) -> Optional[str]:
    """file:// URI for a violation path, or None when one can't be built."""
    try:
        path = Path(file_path)
        if not path.is_absolute():
            path = path.resolve()
        return path.as_uri()
    except (OSError, ValueError):
        return None


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
    color: bool = False,
    hyperlinks: bool = False,
) -> str:
    show_info = should_show_info(verbose, fail_level)
    red = "\033[91m" if color else ""
    yellow = "\033[93m" if color else ""
    blue = "\033[94m" if color else ""
    green = "\033[92m" if color else ""
    bold = "\033[1m" if color else ""
    dim = "\033[2m" if color else ""
    reset = "\033[0m" if color else ""

    errors, warnings, info = get_counts(violations)

    errors_list = [v for v in violations if v.severity == Severity.ERROR]
    warnings_list = [v for v in violations if v.severity == Severity.WARNING]
    info_list = [v for v in violations if v.severity == Severity.INFO]

    # Synthetic rule IDs (e.g. invalid-config) have no documentation page —
    # only link rules that actually ran as builtins.
    builtin_ids = {r.rule_id for r in rules if getattr(r, "_source", "builtin") == "builtin"}

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
            loc_text = f"{rel}:{v.file_line}" if v.file_line else rel
            if hyperlinks:
                uri = _file_uri(v.file_path)
                if uri:
                    loc_text = _osc8(uri, loc_text)
            location = f" [{loc_text}]"
        rule_ref = v.rule_id
        if hyperlinks and v.rule_id in builtin_ids:
            rule_ref = _osc8(rule_doc_url(v.rule_id), v.rule_id)
        return (
            f"{icon} {v.severity.value.upper()} ({rule_ref}){fix_marker(v)}{location}: {v.message}"
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
    documented = sorted({v.rule_id for v in shown if v.rule_id in builtin_ids})
    if documented:
        if hyperlinks:
            # Rule ids above are clickable — the per-rule URL list is noise.
            output.append(
                f"\n{dim}Rule ids link to their docs — or run"
                f" `skillsaw explain <rule-id>`.{reset}"
            )
        else:
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
        output.append(f"  {dim}Baseline: {baseline_suppressed} suppressed{reset}")
    if grade is not None:
        grade_color = {"A": green, "B": green, "C": yellow, "D": red, "F": red}[grade.letter[0]]
        output.append(
            f"  Grade:    {grade_color}{bold}{grade.letter}{reset} "
            f"({grade.density:.2f} weighted violations per 10k tokens)"
        )
        if grade.info and not show_info:
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
