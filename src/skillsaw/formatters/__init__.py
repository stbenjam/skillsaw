"""
Output formatters for skillsaw lint results.

Supported formats: text, json, sarif, html.
"""

from typing import List

from ..rule import Rule, RuleViolation

FORMATS = ("text", "json", "sarif", "html")

EXTENSION_MAP = {
    ".json": "json",
    ".sarif": "sarif",
    ".html": "html",
    ".htm": "html",
}


def infer_format(filename: str) -> str:
    """Infer output format from file extension. Raises ValueError if unknown."""
    from pathlib import Path

    ext = Path(filename).suffix.lower()
    if ext not in EXTENSION_MAP:
        raise ValueError(
            f"Cannot infer format from extension '{ext}'. "
            f"Supported: {', '.join(sorted(EXTENSION_MAP))}"
        )
    return EXTENSION_MAP[ext]


def get_counts(violations: List[RuleViolation]):
    """Count violations by severity."""
    from ..rule import Severity

    errors = sum(1 for v in violations if v.severity == Severity.ERROR)
    warnings = sum(1 for v in violations if v.severity == Severity.WARNING)
    info = sum(1 for v in violations if v.severity == Severity.INFO)
    return errors, warnings, info


def format_report(
    fmt: str,
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
) -> str:
    """
    Format lint results in the specified format.

    Args:
        fmt: One of "text", "json", "sarif", "html"
        violations: Violations from linter.run()
        context: RepositoryContext
        rules: List of Rule instances that were run
        version: skillsaw version string
        verbose: Include extra detail (info-level messages, expanded stats)
    """
    if fmt == "text":
        from .text import format_text

        return format_text(violations, context, rules, version, verbose)
    elif fmt == "json":
        from .json_fmt import format_json

        return format_json(violations, context, rules, version, verbose)
    elif fmt == "sarif":
        from .sarif import format_sarif

        return format_sarif(violations, context, rules, version, verbose)
    elif fmt == "html":
        from .html import format_html

        return format_html(violations, context, rules, version, verbose)
    else:
        raise ValueError(f"Unknown format: {fmt}. Supported: {', '.join(FORMATS)}")
