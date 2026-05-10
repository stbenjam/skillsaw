"""JSON output formatter for skillsaw lint results."""

import json
from typing import List

from ..rule import Rule, RuleViolation, Severity
from . import get_counts, relative_path


def format_json(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
) -> str:
    errors, warnings, info = get_counts(violations)

    repo_types_list = sorted(t.value for t in context.repo_types)

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
            }
            for v in violations
            if verbose or v.severity != Severity.INFO
        ],
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "info": info,
        },
    }

    return json.dumps(report, indent=2)
