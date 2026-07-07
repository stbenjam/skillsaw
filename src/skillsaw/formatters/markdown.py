"""GitHub-flavored-markdown report formatter.

A compact report card suitable for ``$GITHUB_STEP_SUMMARY``, PR comments, or
any other markdown sink: summary counts, the quality grade when available,
and a violations table — truncated politely for huge repos.
"""

from typing import List, Optional

from ..rule import Rule, RuleViolation, Severity
from . import get_counts, relative_path, should_show_info

# Keep step summaries readable (and under GitHub's 1 MiB summary cap) on
# huge repos: show at most this many table rows, then a truncation note.
MAX_TABLE_ROWS = 100

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_SEVERITY_ICON = {"error": "✗", "warning": "⚠", "info": "ℹ"}


def _escape_cell(value: str) -> str:
    """Escape text for a GFM table cell: HTML, pipes, and newlines."""
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace("|", "\\|")
    return value.replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")


def format_markdown(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
    baseline_suppressed: int = 0,
    grade=None,
    fail_level: str = "error",
) -> str:
    show_info = should_show_info(verbose, fail_level)
    errors, warnings, info = get_counts(violations)

    output = ["## skillsaw report", ""]

    counts = [
        f"**{errors}** error{'' if errors == 1 else 's'}",
        f"**{warnings}** warning{'' if warnings == 1 else 's'}",
    ]
    if show_info:
        counts.append(f"**{info}** info")
    output.append(" · ".join(counts))
    output.append("")

    if grade is not None:
        output.append(
            f"**Grade: {grade.letter}** "
            f"({grade.density:.2f} weighted violations per 10k tokens)"
        )
        output.append("")

    shown = [v for v in violations if show_info or v.severity != Severity.INFO]
    shown.sort(
        key=lambda v: (
            _SEVERITY_ORDER[v.severity.value],
            str(v.file_path or ""),
            v.file_line or 0,
            v.rule_id,
        )
    )

    if shown:
        output.append("| Severity | Rule | Location | Message |")
        output.append("| --- | --- | --- | --- |")
        for v in shown[:MAX_TABLE_ROWS]:
            icon = _SEVERITY_ICON[v.severity.value]
            rel = relative_path(v.file_path, context.root_path)
            location = ""
            if rel:
                location = f"`{_escape_cell(rel)}`"
                line = v.file_line
                if line is not None and line >= 1:
                    location = f"`{_escape_cell(rel)}:{line}`"
            output.append(
                f"| {icon} {v.severity.value} "
                f"| `{_escape_cell(v.rule_id)}` "
                f"| {location} "
                f"| {_escape_cell(v.message)} |"
            )
        output.append("")
        if len(shown) > MAX_TABLE_ROWS:
            remaining = len(shown) - MAX_TABLE_ROWS
            output.append(
                f"_...and {remaining} more violation{'' if remaining == 1 else 's'} "
                "not shown — run `skillsaw lint` locally for the full report._"
            )
            output.append("")
    else:
        output.append("**✓ All checks passed!**")
        output.append("")

    footnotes = [f"skillsaw {version}", f"{len(rules)} rules"]
    if baseline_suppressed:
        footnotes.append(f"{baseline_suppressed} baseline-suppressed")
    output.append(f"_{' · '.join(footnotes)}_")

    return "\n".join(output)
