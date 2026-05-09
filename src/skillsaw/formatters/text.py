"""
Text output formatter — human-readable terminal output with optional ANSI colors.
"""

import os
from typing import List

from ..rule import Rule, RuleViolation, Severity
from . import get_counts, relative_path


def format_text(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
) -> str:
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

    def fmt_violation(v: RuleViolation) -> str:
        icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}[v.severity.value]
        rel = relative_path(v.file_path, context.root_path)
        location = ""
        if rel:
            location = f" [{rel}:{v.line}]" if v.line else f" [{rel}]"
        return f"{icon} {v.severity.value.upper()}{location}: {v.message}"

    output = []

    if errors_list:
        output.append(f"\n{red}{bold}Errors:{reset}")
        for v in errors_list:
            output.append(f"  {fmt_violation(v)}")

    if warnings_list:
        output.append(f"\n{yellow}{bold}Warnings:{reset}")
        for v in warnings_list:
            output.append(f"  {fmt_violation(v)}")

    if verbose and info_list:
        output.append(f"\n{blue}{bold}Info:{reset}")
        for v in info_list:
            output.append(f"  {fmt_violation(v)}")

    output.append(f"\n{bold}Scanned:{reset}")
    repo_types_str = ", ".join(sorted(t.value for t in context.repo_types if t.value != "unknown"))
    output.append(f"  Repo type: {repo_types_str or 'unknown'}")
    output.append(f"  Plugins:   {len(context.plugins)}")
    output.append(f"  Skills:    {len(context.skills)}")
    output.append(f"  Rules run: {len(rules)}")

    output.append(f"\n{bold}Summary:{reset}")
    output.append(f"  {red}Errors:   {errors}{reset}")
    output.append(f"  {yellow}Warnings: {warnings}{reset}")
    if verbose:
        output.append(f"  {blue}Info:     {info}{reset}")

    if errors == 0 and warnings == 0:
        output.append(f"\n{green}{bold}✓ All checks passed!{reset}")

    return "\n".join(output)
