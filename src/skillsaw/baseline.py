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
    value: Optional[float] = None
    baseline_mode: Optional[str] = None


@dataclass
class BaselineFile:
    version: str
    generated_by: str
    generated_at: str
    violations: List[BaselineEntry] = field(default_factory=list)


def _read_file_lines(path: Path, cache: Dict[Path, Optional[List[str]]]) -> Optional[List[str]]:
    try:
        resolved = path.resolve()
    except OSError:
        return None
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

    # Ratchet violations use rule_id + file_path only so the fingerprint
    # is stable across value changes (e.g. token count going up or down).
    if violation.value is not None and rel_path is not None:
        raw = f"{rule_id}\0{rel_path}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    if rel_path is not None and file_line is not None and violation.file_path is not None:
        file_path = violation.file_path
        if not file_path.is_absolute():
            file_path = root_path / file_path
        lines = _read_file_lines(file_path, _file_cache)
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
    baseline_modes: Optional[Dict[str, str]] = None,
) -> BaselineFile:
    file_cache: Dict[Path, Optional[List[str]]] = {}
    modes = baseline_modes or {}
    entries: List[BaselineEntry] = []

    for v in violations:
        fp = fingerprint_violation(v, root_path, _file_cache=file_cache)
        mode = modes.get(v.rule_id)
        entries.append(
            BaselineEntry(
                fingerprint=fp,
                rule_id=v.rule_id,
                file_path=relative_path(v.file_path, root_path),
                line=v.file_line,
                message=v.message,
                severity=v.severity.value,
                value=v.value,
                baseline_mode=mode if v.value is not None else None,
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
        "violations": [
            {k: v for k, v in asdict(e).items() if v is not None} for e in baseline.violations
        ],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> BaselineFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid baseline JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Invalid baseline JSON in {path}: expected a JSON object")

    version = data.get("version")
    if version != _BASELINE_VERSION:
        raise ValueError(
            f"Unsupported baseline version '{version}' in {path} "
            f"(expected '{_BASELINE_VERSION}')"
        )

    violations_data = data.get("violations", [])
    if not isinstance(violations_data, list):
        raise ValueError(f"Invalid baseline JSON in {path}: 'violations' must be a list")

    entries = []
    for i, v in enumerate(violations_data):
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
                value=v.get("value"),
                baseline_mode=v.get("baseline_mode"),
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


def _is_worse(current_value: float, baseline_value: float, mode: str) -> bool:
    if mode == "ceiling":
        return current_value > baseline_value
    if mode == "floor":
        return current_value < baseline_value
    return False


def filter_baselined_violations(
    violations: List[RuleViolation],
    baseline: BaselineFile,
    root_path: Path,
) -> Tuple[List[RuleViolation], List[BaselineEntry]]:
    """Subtract baselined violations and report stale entries.

    Returns ``(kept, stale)`` where *kept* are violations not in the
    baseline (new violations) and *stale* are baseline entries that no
    longer match any current violation.

    Ratchet entries (those with ``value`` and ``baseline_mode``) use
    value comparison: a violation is only suppressed if it is equal to
    or better than the baselined value.
    """
    # Separate ratchet entries from regular fingerprint entries.
    ratchet_entries: Dict[str, BaselineEntry] = {}
    regular_budget = Counter()
    for e in baseline.violations:
        if e.value is not None and e.baseline_mode:
            ratchet_entries[e.fingerprint] = e
        else:
            regular_budget[e.fingerprint] += 1

    file_cache: Dict[Path, Optional[List[str]]] = {}
    kept: List[RuleViolation] = []
    consumed_ratchet: set = set()

    for v in violations:
        fp = fingerprint_violation(v, root_path, _file_cache=file_cache)

        if fp in ratchet_entries:
            entry = ratchet_entries[fp]
            if v.value is not None and _is_worse(v.value, entry.value, entry.baseline_mode):
                kept.append(v)
            else:
                consumed_ratchet.add(fp)
        elif regular_budget[fp] > 0:
            regular_budget[fp] -= 1
        else:
            kept.append(v)

    # Stale entries: unconsumed regular + unconsumed ratchet.
    remaining = dict(regular_budget)
    stale: List[BaselineEntry] = []
    for entry in baseline.violations:
        fp = entry.fingerprint
        if entry.value is not None and entry.baseline_mode:
            if fp not in consumed_ratchet:
                stale.append(entry)
        elif remaining.get(fp, 0) > 0:
            remaining[fp] -= 1
            stale.append(entry)

    return kept, stale
