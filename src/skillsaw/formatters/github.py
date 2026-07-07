"""GitHub Actions workflow-command output formatter.

Emits ``::error`` / ``::warning`` / ``::notice`` workflow commands that GitHub
Actions turns into PR annotations when printed to a step's stdout. See
https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions

GitHub renders at most 10 error and 10 warning annotations per step (and 10
notices), so output is capped per severity and truncation is reported with a
single trailing ``::notice`` — never silently.
"""

import os
from pathlib import Path, PurePath
from typing import List, Optional

from ..rule import Rule, RuleViolation, Severity
from . import relative_path, should_show_info

# GitHub Actions shows at most this many annotations per step for each of
# the error, warning, and notice levels; anything beyond is dropped.
ANNOTATION_LIMIT = 10

_SEVERITY_COMMAND = {
    "error": "error",
    "warning": "warning",
    "info": "notice",
}


def _escape_data(value: str) -> str:
    """Escape a workflow-command message (the part after ``::``).

    ``%`` must be escaped first so already-escaped sequences aren't
    double-escaped.
    """
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """Escape a workflow-command property value (``file=``, ``title=``, ...).

    Properties additionally need ``,`` and ``:`` escaped — they delimit
    properties and the command itself.
    """
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def _annotation_path(file_path: Optional[Path], root: Path) -> Optional[str]:
    """Path for the ``file=`` property, as GitHub expects it.

    Annotations only attach to files when ``file=`` is relative to
    ``GITHUB_WORKSPACE`` — not to the lint root, which may be a
    subdirectory of the checkout. When ``GITHUB_WORKSPACE`` is set and the
    file lives under it, relativize against the workspace; otherwise fall
    back to the lint root (identical when the action lints the whole
    checkout, and the best available answer outside CI).
    """
    if file_path is None:
        return None
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        absolute = file_path if file_path.is_absolute() else root / file_path
        try:
            return absolute.resolve().relative_to(Path(workspace).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    rel = relative_path(file_path, root)
    return PurePath(rel).as_posix() if rel else None


def _format_command(v: RuleViolation, root: Path) -> str:
    command = _SEVERITY_COMMAND[v.severity.value]
    properties = []
    rel = _annotation_path(v.file_path, root)
    if rel:
        properties.append(f"file={_escape_property(rel)}")
        line = v.file_line
        if line is not None and line >= 1:
            properties.append(f"line={line}")
    properties.append(f"title={_escape_property(v.rule_id)}")
    return f"::{command} {','.join(properties)}::{_escape_data(v.message)}"


def format_github(
    violations: List[RuleViolation],
    context,
    rules: List[Rule],
    version: str,
    verbose: bool = False,
    fail_level: str = "error",
) -> str:
    show_info = should_show_info(verbose, fail_level)

    errors = [v for v in violations if v.severity == Severity.ERROR]
    warnings = [v for v in violations if v.severity == Severity.WARNING]
    info = [v for v in violations if v.severity == Severity.INFO] if show_info else []

    hidden = max(0, len(errors) - ANNOTATION_LIMIT) + max(0, len(warnings) - ANNOTATION_LIMIT)
    # The truncation notice shares the notice budget with info annotations:
    # when one is needed, keep a slot free so it isn't dropped too.
    info_limit = ANNOTATION_LIMIT
    if hidden or len(info) > ANNOTATION_LIMIT:
        info_limit = ANNOTATION_LIMIT - 1
    hidden += max(0, len(info) - info_limit)

    lines = []
    for group, limit in (
        (errors, ANNOTATION_LIMIT),
        (warnings, ANNOTATION_LIMIT),
        (info, info_limit),
    ):
        for v in group[:limit]:
            lines.append(_format_command(v, context.root_path))

    if hidden:
        plural = "" if hidden == 1 else "s"
        lines.append(
            "::notice title=skillsaw::"
            + _escape_data(
                f"...and {hidden} more violation{plural} not annotated "
                "(GitHub caps annotations per step); see the log or report for the full list."
            )
        )

    return "\n".join(lines)
