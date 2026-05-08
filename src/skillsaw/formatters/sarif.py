"""SARIF v2.1.0 output formatter."""

import json
from typing import List

from ..rule import Rule, RuleViolation

_SEVERITY_MAP = {
    "error": "error",
    "warning": "warning",
    "info": "note",
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

    results = []
    for v in violations:
        result = {
            "ruleId": v.rule_id,
            "level": _SEVERITY_MAP.get(v.severity.value, "warning"),
            "message": {"text": v.message},
        }
        if v.file_path is not None:
            try:
                rel = v.file_path.relative_to(context.root_path)
            except (ValueError, TypeError):
                rel = str(v.file_path)
            location = {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": str(rel),
                        "uriBaseId": "%SRCROOT%",
                    },
                },
            }
            if v.line is not None:
                location["physicalLocation"]["region"] = {"startLine": v.line}
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
                        "plugins": len(context.plugins),
                        "skills": len(context.skills),
                        "rules_run": len(rules),
                    },
                },
            },
        ],
    }

    return json.dumps(sarif, indent=2)
