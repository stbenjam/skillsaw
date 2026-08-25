"""Code Climate / GitLab Code Quality JSON output formatter."""

import hashlib
import json
from typing import List

from ..rule import RuleViolation, Severity
from . import relative_path, should_show_info

_SEVERITY_MAP = {
    "error": "critical",
    "warning": "major",
    "info": "minor",
}


def format_code_climate(
    violations: List[RuleViolation],
    context,
    rules,
    version: str,
    verbose: bool = False,
    fail_level: str = "error",
) -> str:
    show_info = should_show_info(verbose, fail_level)
    filtered = violations if show_info else [v for v in violations if v.severity != Severity.INFO]

    items = []
    for v in filtered:
        rel = relative_path(v.file_path, context.root_path)
        if rel and rel.startswith("./"):
            rel = rel[2:]

        fingerprint_input = f"{v.rule_id}:{rel or ''}:{v.file_line or ''}"
        if v.fingerprint_discriminator:
            fingerprint_input += f":{v.fingerprint_discriminator}"
        # "surrogatepass" matches baseline.py's fingerprint encoding: the
        # discriminator can carry raw config keys, and a quoted YAML key
        # like "\uD800bad" materializes a lone surrogate that a strict
        # encode would crash on.
        fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8", "surrogatepass")).hexdigest()

        entry = {
            "description": v.message,
            "check_name": v.rule_id,
            "fingerprint": fingerprint,
            "severity": _SEVERITY_MAP.get(v.severity.value, "major"),
            "location": {
                "path": rel or "",
                "lines": {
                    "begin": v.file_line if v.file_line and v.file_line >= 1 else 1,
                },
            },
        }
        items.append(entry)

    return json.dumps(items, indent=2)
