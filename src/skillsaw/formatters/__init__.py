"""
Output formatters for skillsaw lint results.

Supported formats: text, json, sarif, html, code-climate (alias: gitlab).
"""

from pathlib import Path
from typing import List, Optional

from ..rule import Rule, RuleViolation

FORMATS = ("text", "json", "sarif", "html", "code-climate", "gitlab")


def relative_path(file_path: Optional[Path], root: Path) -> Optional[str]:
    """Relativize a file path to the repo root. Falls back to str() if not under root."""
    if file_path is None:
        return None
    try:
        return str(file_path.relative_to(root))
    except (ValueError, TypeError):
        return str(file_path)


EXTENSION_MAP = {
    ".json": "json",
    ".sarif": "sarif",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
}

_FORMAT_SET = set(FORMATS)


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


def parse_output_spec(spec: str) -> tuple:
    """Parse an --output value into (format, filepath).

    Accepts either a bare path (format inferred from extension) or an explicit
    ``FORMAT:PATH`` prefix where FORMAT is a recognised output format name.

    Returns:
        (format_name, filepath_string)

    Raises:
        ValueError: when the format cannot be determined.
    """
    colon = spec.find(":")
    if colon > 0:
        prefix = spec[:colon]
        if prefix in _FORMAT_SET:
            path = spec[colon + 1 :]
            if not path:
                raise ValueError(
                    f"output file path missing after '{prefix}:' "
                    f"(use '{prefix}:FILE', or 'FILE' to infer the format)"
                )
            return prefix, path
    return infer_format(spec), spec


def should_show_info(verbose: bool, fail_level: str) -> bool:
    """Whether info-level violations should be surfaced in a report.

    Info violations are always shown with -v, and also when ``fail-on: info``
    makes them decide the exit code — a failing CI run must show its cause.
    """
    return verbose or fail_level == "info"


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
    baseline_suppressed: int = 0,
    duration: Optional[float] = None,
    grade=None,
    fail_level: str = "error",
    color: bool = False,
    hyperlinks: bool = False,
) -> str:
    """
    Format lint results in the specified format.

    Args:
        fmt: One of "text", "json", "sarif", "html", "code-climate", "gitlab"
        violations: Violations from linter.run()
        context: RepositoryContext
        rules: List of Rule instances that were run
        version: skillsaw version string
        verbose: Include extra detail (info-level messages, expanded stats)
        baseline_suppressed: Number of violations suppressed by baseline
        duration: Wall-clock lint time in seconds (text and json formats only;
            sarif/code-climate schemas have no place for it)
        grade: Optional Grade for the run (text and json formats only)
        fail_level: Effective severity threshold that fails the run — with
            ``fail-on: info`` every format must include the info violations
            that caused the failure even without -v
        color: Emit ANSI colors (text format only — resolved by the caller
            via ``color_enabled()``; file outputs stay plain)
        hyperlinks: Emit OSC 8 terminal hyperlinks (text format only)
    """
    if fmt == "text":
        from .text import format_text

        return format_text(
            violations,
            context,
            rules,
            version,
            verbose,
            baseline_suppressed,
            duration,
            grade,
            fail_level,
            color=color,
            hyperlinks=hyperlinks,
        )
    elif fmt == "json":
        from .json_fmt import format_json

        return format_json(
            violations,
            context,
            rules,
            version,
            verbose,
            baseline_suppressed,
            duration,
            grade,
            fail_level,
        )
    elif fmt == "sarif":
        from .sarif import format_sarif

        return format_sarif(violations, context, rules, version, verbose, fail_level)
    elif fmt == "html":
        from .html import format_html

        return format_html(violations, context, rules, version, verbose, fail_level)
    elif fmt in ("code-climate", "gitlab"):
        from .code_climate import format_code_climate

        return format_code_climate(violations, context, rules, version, verbose, fail_level)
    else:
        raise ValueError(f"Unknown format: {fmt}. Supported: {', '.join(FORMATS)}")
