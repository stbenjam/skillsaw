"""
Baseline support for skillsaw.

A baseline file records existing violations so that ``skillsaw lint`` only
reports *new* violations.  Violations are matched by content-hash fingerprint
(rule ID + relative file path + stripped source-line content) so they survive
line drift caused by unrelated edits elsewhere in the file.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .formatters import relative_path
from .rule import RuleViolation

BASELINE_FILENAME = ".skillsaw-baseline.json"
_BASELINE_VERSION = "1"


@dataclass
class BaselineEntry:
    fingerprint: str
    rule_id: str
    file_path: Optional[str]
    line: Optional[int]
    message: str
    severity: str


@dataclass
class BaselineFile:
    version: str
    generated_by: str
    generated_at: str
    violations: List[BaselineEntry] = field(default_factory=list)


def _read_file_lines(path: Path, cache: Dict[Path, Optional[List[str]]]) -> Optional[List[str]]:
    resolved = path.resolve()
    if resolved not in cache:
        try:
            cache[resolved] = resolved.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            cache[resolved] = None
    return cache[resolved]


def fingerprint_violation(
    violation: RuleViolation,
    root_path: Path,
    *,
    _file_cache: Optional[Dict[Path, Optional[List[str]]]] = None,
) -> str:
    """Compute a content-hash fingerprint for a violation.

    The fingerprint is built from ``rule_id``, relative file path, and the
    stripped content of the source line.  Line numbers are intentionally
    excluded so that the fingerprint survives insertions/deletions elsewhere
    in the file.
    """
    if _file_cache is None:
        _file_cache = {}

    rule_id = violation.rule_id
    rel_path = relative_path(violation.file_path, root_path)
    file_line = violation.file_line

    if rel_path is not None and file_line is not None and violation.file_path is not None:
        lines = _read_file_lines(violation.file_path, _file_cache)
        if lines is not None and 1 <= file_line <= len(lines):
            line_content = lines[file_line - 1].strip()
            raw = f"{rule_id}\0{rel_path}\0{line_content}"
            return hashlib.sha256(raw.encode()).hexdigest()[:16]

    if rel_path is not None:
        raw = f"{rule_id}\0{rel_path}\0{violation.message}"
    else:
        raw = f"{rule_id}\0{violation.message}"

    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_baseline(
    violations: List[RuleViolation],
    root_path: Path,
    version_string: str,
) -> BaselineFile:
    file_cache: Dict[Path, Optional[List[str]]] = {}
    entries: List[BaselineEntry] = []

    for v in violations:
        fp = fingerprint_violation(v, root_path, _file_cache=file_cache)
        entries.append(
            BaselineEntry(
                fingerprint=fp,
                rule_id=v.rule_id,
                file_path=relative_path(v.file_path, root_path),
                line=v.file_line,
                message=v.message,
                severity=v.severity.value,
            )
        )

    return BaselineFile(
        version=_BASELINE_VERSION,
        generated_by=f"skillsaw {version_string}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        violations=entries,
    )


def save_baseline(path: Path, baseline: BaselineFile) -> None:
    data = {
        "version": baseline.version,
        "generated_by": baseline.generated_by,
        "generated_at": baseline.generated_at,
        "violations": [asdict(e) for e in baseline.violations],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> BaselineFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid baseline JSON in {path}: {exc}") from exc

    version = data.get("version")
    if version != _BASELINE_VERSION:
        raise ValueError(
            f"Unsupported baseline version '{version}' in {path} "
            f"(expected '{_BASELINE_VERSION}')"
        )

    entries = []
    for i, v in enumerate(data.get("violations", [])):
        if not isinstance(v, dict) or "fingerprint" not in v:
            raise ValueError(
                f"Baseline entry {i} in {path} is missing required 'fingerprint' field"
            )
        entries.append(
            BaselineEntry(
                fingerprint=v["fingerprint"],
                rule_id=v.get("rule_id", ""),
                file_path=v.get("file_path"),
                line=v.get("line"),
                message=v.get("message", ""),
                severity=v.get("severity", ""),
            )
        )

    return BaselineFile(
        version=version,
        generated_by=data.get("generated_by", ""),
        generated_at=data.get("generated_at", ""),
        violations=entries,
    )


def find_baseline(start_path: Path) -> Optional[Path]:
    """Look for a baseline file in *start_path* and its parents."""
    current = start_path.resolve()
    while current != current.parent:
        candidate = current / BASELINE_FILENAME
        if candidate.exists():
            return candidate
        current = current.parent
    return None


def filter_baselined_violations(
    violations: List[RuleViolation],
    baseline: BaselineFile,
    root_path: Path,
) -> Tuple[List[RuleViolation], List[BaselineEntry]]:
    """Subtract baselined violations and report stale entries.

    Returns ``(kept, stale)`` where *kept* are violations not in the
    baseline (new violations) and *stale* are baseline entries that no
    longer match any current violation.
    """
    budget = Counter(e.fingerprint for e in baseline.violations)
    file_cache: Dict[Path, Optional[List[str]]] = {}
    kept: List[RuleViolation] = []

    for v in violations:
        fp = fingerprint_violation(v, root_path, _file_cache=file_cache)
        if budget[fp] > 0:
            budget[fp] -= 1
        else:
            kept.append(v)

    # budget now holds the *unconsumed* count per fingerprint.  Walk the
    # baseline entries and mark the unconsumed ones as stale.  When a
    # fingerprint has partial consumption (e.g. 3 in baseline, 1 remaining)
    # we mark exactly the surplus entries as stale.
    remaining = dict(budget)
    stale: List[BaselineEntry] = []
    for entry in baseline.violations:
        fp = entry.fingerprint
        if remaining.get(fp, 0) > 0:
            remaining[fp] -= 1
            stale.append(entry)

    return kept, stale
