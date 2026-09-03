"""
Text output formatter — human-readable terminal output with optional ANSI colors.
"""

from pathlib import Path
from typing import List, Optional

from ..rule import AutofixConfidence, Rule, RuleViolation, Severity, severities_at_or_above
from ..rule_docs import rule_doc_url
from ..diagnostics import terminal_safe
from . import get_counts, relative_path, should_show_info
from skillsaw.paths import contained_resolve, safe_resolve

# Below this many displayed findings the severity totals already say where
# the work is; above it a first run scrolls past and needs a triage aid.
TOP_RULES_THRESHOLD = 50

# Five rows is the whole point — a longer list is another wall of text.
TOP_RULES_LIMIT = 5

_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


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


def _file_uri(file_path, root_path: Path) -> Optional[str]:
    """Build a file URI only when the violation path stays inside the repo."""
    try:
        resolved_root = safe_resolve(root_path)
        if resolved_root is None:
            return None
        path = Path(file_path)
        if not path.is_absolute():
            path = resolved_root / path
        contained = contained_resolve(path, resolved_root)
        return contained.as_uri() if contained is not None else None
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
    # Kept last so existing positional callers keep their bindings.
    fix_level: str = "warning",
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
    # What `skillsaw explain` resolves: every builtin rule and the plugin
    # rules that ran. A custom rule from `.skillsaw.yaml` and the linter's
    # own ids (`invalid-config`) have no page to point at.
    from ..rules.builtin import BUILTIN_RULE_REGISTRY

    explainable_ids = set(BUILTIN_RULE_REGISTRY) | {
        r.rule_id for r in rules if getattr(r, "_source", "builtin").startswith("plugin:")
    }

    # Markers mean "skillsaw fix repairs this", so they gate on the fix
    # scope — a shown-but-below-threshold finding stays unmarked.
    scope = severities_at_or_above(fix_level)

    def fix_marker(v: RuleViolation) -> str:
        """Ruff-style fixability marker: [*] safe, [?] needs --suggest."""
        if not v.fixable or v.severity not in scope:
            return ""
        return " [*]" if v.fix_confidence == AutofixConfidence.SAFE else " [?]"

    def fmt_violation(v: RuleViolation) -> str:
        icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}[v.severity.value]
        rel = terminal_safe(relative_path(v.file_path, context.root_path) or "")
        location = ""
        if rel:
            loc_text = f"{rel}:{v.file_line}" if v.file_line else rel
            if hyperlinks:
                uri = _file_uri(v.file_path, context.root_path)
                if uri:
                    loc_text = _osc8(uri, loc_text)
            location = f" [{loc_text}]"
        safe_rule_id = terminal_safe(v.rule_id)
        rule_ref = safe_rule_id
        if hyperlinks and v.rule_id in builtin_ids:
            rule_ref = _osc8(rule_doc_url(v.rule_id), safe_rule_id)
        return (
            f"{icon} {v.severity.value.upper()} ({rule_ref}){fix_marker(v)}{location}: "
            f"{terminal_safe(v.message)}"
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
    output.append(f"  Plugins:   {len(context.distinct_plugin_dirs())}")
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
    # over the marked violations shown above, so marked lines and counts
    # agree (`skillsaw fix` groups per-file fixes and may report different
    # totals).
    fixable_shown = [v for v in shown if v.fixable and v.severity in scope]
    safe_fixable = sum(1 for v in fixable_shown if v.fix_confidence == AutofixConfidence.SAFE)
    suggest_fixable = sum(1 for v in fixable_shown if v.fix_confidence != AutofixConfidence.SAFE)
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

    # Where the findings are concentrated. The totals above say how much
    # there is; these rows say which few rules produced it and what to do
    # about each, so a first run over a large repository is triageable
    # without scrolling back through hundreds of lines.
    if len(shown) >= TOP_RULES_THRESHOLD:
        grouped = {}
        for v in shown:
            grouped.setdefault(v.rule_id, []).append(v)
        ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ranked = ranked[:TOP_RULES_LIMIT]

        severity_color = {Severity.ERROR: red, Severity.WARNING: yellow, Severity.INFO: blue}
        rows = []
        for rule_id, group in ranked:
            severity = min(group, key=lambda v: _SEVERITY_RANK[v.severity]).severity
            files = len({v.file_path for v in group if v.file_path is not None})
            markers = {fix_marker(v).strip() for v in group}
            safe_rule_id = terminal_safe(rule_id)
            if "[*]" in markers:
                hint = f"{green}[*] safe autofix{reset}"
            elif "[?]" in markers:
                hint = f"{green}[?] fix --suggest{reset}"
            elif rule_id in explainable_ids:
                hint = f"{dim}skillsaw explain {safe_rule_id}{reset}"
            elif any(v.source == "custom" for v in group):
                hint = f"{dim}custom rule{reset}"
            else:
                hint = ""
            rows.append(
                {
                    "id": safe_rule_id,
                    "rule_id": rule_id,
                    "count": f"{len(group):,}",
                    "severity": severity,
                    "files": f"{files:,} file{'' if files == 1 else 's'}" if files else "",
                    "hint": hint,
                }
            )

        id_width = max(len(r["id"]) for r in rows)
        count_width = max(len(r["count"]) for r in rows)
        severity_width = max(len(r["severity"].value) for r in rows)
        files_width = max(len(r["files"]) for r in rows)

        top_total = sum(len(group) for _, group in ranked)
        output.append(f"\n{bold}Top rules{reset} ({top_total:,} of {len(shown):,} findings):")
        for r in rows:
            # Pad from the plain id — an OSC 8 link carries invisible bytes
            # that would throw the column alignment off.
            id_cell = r["id"]
            if hyperlinks and r["rule_id"] in builtin_ids:
                id_cell = _osc8(rule_doc_url(r["rule_id"]), id_cell)
            id_cell += " " * (id_width - len(r["id"]))
            severity_cell = severity_color[r["severity"]]
            severity_cell += f"{r['severity'].value.ljust(severity_width)}{reset}"
            cells = [id_cell, r["count"].rjust(count_width), severity_cell]
            # Whole-repository findings carry no path, so the column is
            # dropped rather than left as a gap in every row.
            if files_width:
                cells.append(r["files"].ljust(files_width))
            if r["hint"]:
                cells.append(r["hint"])
            output.append("  " + "  ".join(cells))

    if errors == 0 and warnings == 0 and (fail_level != "info" or info == 0):
        output.append(f"\n{green}{bold}✓ All checks passed!{reset}")

    return "\n".join(output)
