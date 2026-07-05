"""JSON output formatter for skillsaw lint results."""

import json
from typing import List, Optional

from ..rule import Rule, RuleViolation, Severity
from . import get_counts, relative_path


def format_json(
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
    # With fail-on: info the info violations decide the exit code, so a CI
    # report that omitted them would fail with no visible cause.
    show_info = verbose or fail_level == "info"
    errors, warnings, info = get_counts(violations)

    repo_types_list = context.repo_type_names()

    if verbose:
        stats = {
            "repo_type": context.repo_type.value,
            "repo_types": repo_types_list,
            "plugins": [str(p) for p in context.plugins],
            "skills": [str(s) for s in context.skills],
            "rules_run": [r.rule_id for r in rules],
        }
    else:
        stats = {
            "repo_type": context.repo_type.value,
            "repo_types": repo_types_list,
            "plugins": len(context.plugins),
            "skills": len(context.skills),
            "rules_run": len(rules),
        }

    if duration is not None:
        stats["duration_seconds"] = round(duration, 3)

    report = {
        "version": version,
        "stats": stats,
        "violations": [
            {
                "rule_id": v.rule_id,
                "severity": v.severity.value,
                "message": v.message,
                "file_path": relative_path(v.file_path, context.root_path),
                "line": v.file_line,
                "source": v.source,
            }
            for v in violations
            if show_info or v.severity != Severity.INFO
        ],
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "baseline_suppressed": baseline_suppressed,
        },
    }

    if grade is not None:
        report["summary"]["grade"] = grade.to_dict()

    return json.dumps(report, indent=2)
