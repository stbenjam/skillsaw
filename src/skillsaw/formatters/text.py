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

    # Synthetic rule IDs (e.g. invalid-config) have no documentation page —
    # only link rules that actually ran as builtins.
    builtin_ids = {r.rule_id for r in rules if getattr(r, "_source", "builtin") == "builtin"}

    shown = [v for v in violations if v.severity != Severity.INFO or show_info]

    output = []
    _sev_color = {Severity.ERROR: red, Severity.WARNING: yellow, Severity.INFO: blue}
    _sev_icon = {Severity.ERROR: "✗", Severity.WARNING: "⚠", Severity.INFO: "ℹ"}
    _sev_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

    def fix_marker(v: RuleViolation) -> str:
        """Ruff-style fixability marker: [*] safe, [?] needs --suggest."""
        if not v.fixable:
            return ""
        return "[*]" if v.fix_confidence == AutofixConfidence.SAFE else "[?]"

    def _extra_lines_note(extra: List[int]) -> str:
        """Trailing annotation for a collapsed run of identical violations."""
        if not extra:
            return ""
        if len(extra) <= 5:
            joined = ", ".join(str(n) for n in extra)
            label = "line" if len(extra) == 1 else "lines"
            return f"  (also on {label} {joined})"
        return f"  (also on {len(extra)} more lines)"

    if shown:
        # Group by file, then collapse identical (rule, severity, message) runs
        # within a file into one row that lists every line they hit. Files are
        # sorted by path; rows by first line then severity — the same order
        # eslint/ruff settled on.
        by_file = {}
        file_key = {}  # rel -> file_path (for the header hyperlink)
        for v in shown:
            rel = relative_path(v.file_path, context.root_path) or "(no file)"
            by_file.setdefault(rel, {})
            file_key.setdefault(rel, v.file_path)
            key = (v.rule_id, v.severity, v.message)
            group = by_file[rel].get(key)
            if group is None:
                by_file[rel][key] = {
                    "violation": v,
                    "lines": [] if v.file_line is None else [v.file_line],
                }
            elif v.file_line is not None:
                group["lines"].append(v.file_line)

        # Flatten into rows so column widths can be aligned across the report.
        rows = []  # (rel, first_line, severity, rule_id, marker, message)
        for rel in sorted(by_file):
            for group in by_file[rel].values():
                v = group["violation"]
                lines = sorted(group["lines"])
                first = lines[0] if lines else None
                message = v.message + _extra_lines_note(lines[1:])
                rows.append((rel, first, v.severity, v.rule_id, fix_marker(v), message))

        line_w = max((len(str(r[1])) for r in rows if r[1] is not None), default=0)
        rule_w = max(len(r[3]) for r in rows)
        any_marker = any(r[4] for r in rows)

        output.append(f"\n{bold}Violations:{reset}")
        current_file = None
        for rel, first, severity, rule_id, marker, message in sorted(
            rows, key=lambda r: (r[0], r[1] if r[1] is not None else -1, _sev_order[r[2]])
        ):
            if rel != current_file:
                current_file = rel
                header = rel
                if hyperlinks and file_key[rel] is not None:
                    uri = _file_uri(file_key[rel])
                    if uri:
                        header = _osc8(uri, rel)
                output.append(f"\n{bold}{header}{reset}")

            sc = _sev_color[severity]
            line_txt = "" if first is None else str(first)
            sev_cell = f"{sc}{_sev_icon[severity]} {severity.value:<7}{reset}"
            rule_pad = " " * (rule_w - len(rule_id))
            if hyperlinks and rule_id in builtin_ids:
                rule_cell = _osc8(rule_doc_url(rule_id), rule_id) + rule_pad
            else:
                rule_cell = rule_id + rule_pad
            marker_cell = ""
            if any_marker:
                marker_cell = f"  {green}{marker:<3}{reset}" if marker else "     "
            output.append(
                f"  {line_txt:>{line_w}}  {sev_cell}  {rule_cell}{marker_cell}  {message}"
            )

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

    # Legend for the [*]/[?] markers and the lint-to-fix hint. Counts are over
    # the violations shown above; a collapsed row may cover several fixable
    # violations under one marker, so the count can exceed the visible markers
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


def format_statistics(
    violations: List[RuleViolation],
    verbose: bool = False,
    fail_level: str = "error",
    color: bool = False,
) -> str:
    """Ruff-style per-rule violation counts, highest first.

    Text-format only; counts the same violations the report shows (info
    included only with -v or ``fail-on: info``). Returns "" when nothing is
    shown so the caller can skip printing.
    """
    show_info = should_show_info(verbose, fail_level)
    shown = [v for v in violations if v.severity != Severity.INFO or show_info]
    if not shown:
        return ""

    bold = "\033[1m" if color else ""
    dim = "\033[2m" if color else ""
    reset = "\033[0m" if color else ""

    counts = {}
    for v in shown:
        counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    count_w = max(len(str(c)) for _, c in ranked)

    lines = [f"{bold}Statistics:{reset}"]
    for rule_id, count in ranked:
        lines.append(f"  {count:>{count_w}}  {rule_id}")
    lines.append(f"  {dim}{len(shown)} violation(s) across {len(ranked)} rule(s){reset}")
    return "\n".join(lines)
