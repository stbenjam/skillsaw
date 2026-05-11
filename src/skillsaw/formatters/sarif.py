"""SARIF v2.1.0 output formatter."""

import json
from typing import List

from ..rule import Rule, RuleViolation, Severity
from . import relative_path

_SEVERITY_MAP = {
    "error": "error",
    "warning": "warning",
    "info": "note",
}

# Human-readable descriptions for synthetic rule IDs that have no backing
# Rule instance (e.g. "invalid-config" emitted by Linter._validate_config).
_SYNTHETIC_DESCRIPTIONS = {
    "invalid-config": "Unknown rule ID in configuration",
}


def format_sarif(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
) -> str:
    seen = {}
    for r in rules:
        if r.rule_id not in seen:
            seen[r.rule_id] = {
                "id": r.rule_id,
                "shortDescription": {"text": r.description},
            }

    # Add synthetic descriptors for violations whose rule_id has no
    # matching Rule instance (e.g. "invalid-config" from _validate_config).
    # SARIF consumers that enforce referential integrity require every
    # ruleId referenced by a result to appear in runs[].tool.driver.rules[].
    for v in violations:
        if v.rule_id not in seen:
            seen[v.rule_id] = {
                "id": v.rule_id,
                "shortDescription": {
                    "text": _SYNTHETIC_DESCRIPTIONS.get(v.rule_id, v.rule_id),
                },
            }

    results = []
    filtered = violations if verbose else [v for v in violations if v.severity != Severity.INFO]
    for v in filtered:
        result = {
            "ruleId": v.rule_id,
            "level": _SEVERITY_MAP.get(v.severity.value, "warning"),
            "message": {"text": v.message},
        }
        rel = relative_path(v.file_path, context.root_path)
        if rel is not None:
            location = {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": rel,
                        "uriBaseId": "%SRCROOT%",
                    },
                },
            }
            fl = v.file_line
            if fl is not None and fl >= 1:
                location["physicalLocation"]["region"] = {"startLine": fl}
            result["locations"] = [location]
        results.append(result)

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "skillsaw",
                        "version": version,
                        "informationUri": "https://github.com/stbenjam/skillsaw",
                        "rules": list(seen.values()),
                    },
                },
                "results": results,
                "properties": {
                    "stats": {
                        "repo_type": context.repo_type.value,
                        "repo_types": sorted(t.value for t in context.repo_types),
                        "plugins": len(context.plugins),
                        "skills": len(context.skills),
                        "rules_run": len(rules),
                    },
                },
            },
        ],
    }

    return json.dumps(sarif, indent=2)
