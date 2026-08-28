"""
Text output formatter — human-readable terminal output with optional ANSI colors.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..rule import AutofixConfidence, Rule, RuleViolation, Severity
from ..rule_docs import rule_doc_url
from ..diagnostics import terminal_safe
from . import get_counts, relative_path, should_show_info
from skillsaw.paths import contained_resolve, safe_resolve

_COLLAPSE_THRESHOLD = 3


@dataclass(frozen=True)
class _TextDiagnostic:
    """One human-facing row anchored to a real violation."""

    violation: RuleViolation
    message: str
    file_path: Optional[Path]
    file_line: Optional[int]

    @classmethod
    def individual(cls, violation: RuleViolation) -> "_TextDiagnostic":
        return cls(
            violation=violation,
            message=violation.message,
            file_path=violation.file_path,
            file_line=violation.file_line,
        )


# A strategy receives positions for one rule and returns presentation-only
# replacements. ``None`` hides a later row whose violations are represented
# by the diagnostic at the group's first position. The original violation
# list is never changed and remains authoritative for counts, baselines, exit
# status, and every structured formatter.
_TextCollapsePlan = Dict[int, Optional[_TextDiagnostic]]
_TextCollapseStrategy = Callable[[Sequence[Tuple[int, RuleViolation]], object], _TextCollapsePlan]


def _absolute_path(path: Path, root_path: Path) -> Path:
    return path if path.is_absolute() else root_path / path


def _skill_subtree(violation: RuleViolation, context) -> Optional[Tuple[Path, str]]:
    """Return the first directory below the containing skill, if any."""
    if violation.file_path is None:
        return None
    violation_path = _absolute_path(violation.file_path, context.root_path)
    matches = []
    for skill in context.skills:
        skill_path = _absolute_path(Path(skill), context.root_path)
        try:
            relative = violation_path.relative_to(skill_path)
        except ValueError:
            continue
        if len(relative.parts) >= 2:
            matches.append((len(skill_path.parts), skill_path, relative.parts[0]))
    if not matches:
        return None
    _, skill_path, directory = max(matches, key=lambda match: match[0])
    return skill_path / directory, f"{directory}/"


def _collapse_unreferenced_skill_files(
    indexed: Sequence[Tuple[int, RuleViolation]], context
) -> _TextCollapsePlan:
    """Collapse unreferenced files sharing a skill's top-level subtree."""
    grouped = defaultdict(list)
    for position, violation in indexed:
        subtree = _skill_subtree(violation, context)
        if subtree is None:
            continue
        subtree_path, label = subtree
        # Keep differently configured severities and presentation metadata
        # isolated even though a normal run gives this rule one severity.
        key = (
            subtree_path,
            label,
            violation.severity,
            violation.source,
            violation.fixable,
            violation.fix_confidence,
        )
        grouped[key].append((position, violation))

    plan: _TextCollapsePlan = {}
    for (subtree_path, label, *_), members in grouped.items():
        if len(members) < _COLLAPSE_THRESHOLD:
            continue
        first_position = members[0][0]
        plan[first_position] = _TextDiagnostic(
            violation=members[0][1],
            message=(
                f"{len(members)} files under '{label}' are never referenced from "
                "SKILL.md (directly or transitively)"
            ),
            file_path=subtree_path,
            file_line=None,
        )
        for position, _ in members[1:]:
            plan[position] = None
    return plan


_TEXT_COLLAPSE_STRATEGIES: Dict[str, _TextCollapseStrategy] = {
    "agentskill-unreferenced-files": _collapse_unreferenced_skill_files,
}


def _text_diagnostics(violations: Sequence[RuleViolation], context) -> List[_TextDiagnostic]:
    """Build presentation rows without changing the underlying findings."""
    by_rule = defaultdict(list)
    for position, violation in enumerate(violations):
        if violation.rule_id in _TEXT_COLLAPSE_STRATEGIES:
            by_rule[violation.rule_id].append((position, violation))

    plan: _TextCollapsePlan = {}
    for rule_id, indexed in by_rule.items():
        plan.update(_TEXT_COLLAPSE_STRATEGIES[rule_id](indexed, context))

    diagnostics = []
    for position, violation in enumerate(violations):
        if position not in plan:
            diagnostics.append(_TextDiagnostic.individual(violation))
        elif plan[position] is not None:
            diagnostics.append(plan[position])
    return diagnostics


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

    def fmt_violation(diagnostic: _TextDiagnostic) -> str:
        v = diagnostic.violation
        icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}[v.severity.value]
        rel = terminal_safe(relative_path(diagnostic.file_path, context.root_path) or "")
        location = ""
        if rel:
            loc_text = f"{rel}:{diagnostic.file_line}" if diagnostic.file_line else rel
            if hyperlinks:
                uri = _file_uri(diagnostic.file_path, context.root_path)
                if uri:
                    loc_text = _osc8(uri, loc_text)
            location = f" [{loc_text}]"
        safe_rule_id = terminal_safe(v.rule_id)
        rule_ref = safe_rule_id
        if hyperlinks and v.rule_id in builtin_ids:
            rule_ref = _osc8(rule_doc_url(v.rule_id), safe_rule_id)
        return (
            f"{icon} {v.severity.value.upper()} ({rule_ref}){fix_marker(v)}{location}: "
            f"{terminal_safe(diagnostic.message)}"
        )

    output = []

    if errors_list:
        output.append(f"\n{red}{bold}Errors:{reset}")
        for diagnostic in _text_diagnostics(errors_list, context):
            output.append(f"  {fmt_violation(diagnostic)}")

    if warnings_list:
        output.append(f"\n{yellow}{bold}Warnings:{reset}")
        for diagnostic in _text_diagnostics(warnings_list, context):
            output.append(f"  {fmt_violation(diagnostic)}")

    if show_info and info_list:
        output.append(f"\n{blue}{bold}Info:{reset}")
        for diagnostic in _text_diagnostics(info_list, context):
            output.append(f"  {fmt_violation(diagnostic)}")

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
