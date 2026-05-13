"""
Inline suppression directives for skillsaw.

Parses HTML comment directives in markdown content to allow surgical
suppression of specific rules at specific lines:

    <!-- skillsaw-disable rule-id -->
    ...suppressed content...
    <!-- skillsaw-enable rule-id -->

    <!-- skillsaw-disable-next-line rule-id -->
    This single line is suppressed.

    <!-- skillsaw-disable rule-a, rule-b -->
    <!-- skillsaw-enable -->  (re-enables all)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set

# Matches <!-- skillsaw-disable rule-a, rule-b --> or <!-- skillsaw-disable -->
_DISABLE_RE = re.compile(
    r"<!--\s*skillsaw-disable\s*([\w,\s-]*?)\s*-->",
    re.IGNORECASE,
)

# Matches <!-- skillsaw-disable-next-line rule-a, rule-b -->
_DISABLE_NEXT_LINE_RE = re.compile(
    r"<!--\s*skillsaw-disable-next-line\s+([\w,\s-]+?)\s*-->",
    re.IGNORECASE,
)

# Matches <!-- skillsaw-enable rule-a, rule-b --> or <!-- skillsaw-enable -->
_ENABLE_RE = re.compile(
    r"<!--\s*skillsaw-enable\s*([\w,\s-]*?)\s*-->",
    re.IGNORECASE,
)


def _parse_rule_ids(raw: str) -> List[str]:
    """Parse comma-separated rule IDs from a directive."""
    return [rid.strip() for rid in raw.split(",") if rid.strip()]


@dataclass
class SuppressionMap:
    """Tracks which rule IDs are suppressed at which file lines."""

    # Maps file line number -> set of suppressed rule IDs
    _suppressed_lines: Dict[int, FrozenSet[str]] = field(default_factory=dict)
    # Set of lines where ALL rules are suppressed (empty rule list in disable)
    _fully_suppressed_lines: Set[int] = field(default_factory=set)

    def is_suppressed(self, rule_id: str, file_line: int) -> bool:
        """Check if a rule is suppressed at a given file line number."""
        if file_line in self._fully_suppressed_lines:
            return True
        suppressed = self._suppressed_lines.get(file_line)
        if suppressed and rule_id in suppressed:
            return True
        return False


def build_suppression_map(content: str, line_offset: int = 0) -> SuppressionMap:
    """Parse suppression directives from file content.

    Args:
        content: Full file content (including frontmatter etc.)
        line_offset: Offset to add to body-relative line numbers to get file lines.
                     For files without frontmatter this is 0.

    Returns:
        SuppressionMap that can check if a rule is suppressed at a given line.
    """
    lines = content.splitlines()

    # Track currently disabled rule IDs
    disabled: Set[str] = set()
    # Whether "disable all" is currently active (bare <!-- skillsaw-disable -->)
    disable_all_active: bool = False

    # Per-line suppression data
    suppressed_lines: Dict[int, Set[str]] = {}
    fully_suppressed_lines: Set[int] = set()

    # Lines where disable-next-line applies
    next_line_rules: Optional[List[str]] = None

    for line_num_0, line in enumerate(lines):
        file_line = line_num_0 + 1 + line_offset  # 1-based, adjusted for offset

        # Check for disable-next-line first (takes precedence)
        m_next = _DISABLE_NEXT_LINE_RE.search(line)
        if m_next:
            next_line_rules = _parse_rule_ids(m_next.group(1))
            continue

        # Check for enable directive
        m_enable = _ENABLE_RE.search(line)
        if m_enable:
            rule_ids_str = m_enable.group(1).strip()
            if rule_ids_str:
                # Re-enable specific rules
                for rid in _parse_rule_ids(rule_ids_str):
                    disabled.discard(rid)
            else:
                # Re-enable all
                disabled.clear()
                disable_all_active = False
            # Process any next-line suppression from previous line
            if next_line_rules is not None:
                suppressed_lines.setdefault(file_line, set()).update(next_line_rules)
                next_line_rules = None
            continue

        # Check for disable directive
        m_disable = _DISABLE_RE.search(line)
        if m_disable:
            rule_ids = _parse_rule_ids(m_disable.group(1))
            if rule_ids:
                disabled.update(rule_ids)
            else:
                # Bare <!-- skillsaw-disable --> suppresses all rules
                disable_all_active = True
            # Process any next-line suppression from previous line
            if next_line_rules is not None:
                suppressed_lines.setdefault(file_line, set()).update(next_line_rules)
                next_line_rules = None
            continue

        # Apply next-line suppression from previous iteration
        if next_line_rules is not None:
            suppressed_lines.setdefault(file_line, set()).update(next_line_rules)
            next_line_rules = None

        # Apply "disable all" to this line
        if disable_all_active:
            fully_suppressed_lines.add(file_line)

        # Apply current disabled rules to this line
        if disabled:
            suppressed_lines.setdefault(file_line, set()).update(disabled)

    # Convert to frozen sets for the map
    frozen: Dict[int, FrozenSet[str]] = {
        line: frozenset(rules) for line, rules in suppressed_lines.items()
    }

    return SuppressionMap(
        _suppressed_lines=frozen,
        _fully_suppressed_lines=frozenset(fully_suppressed_lines),
    )


def build_suppression_map_for_file(file_path: Path) -> Optional[SuppressionMap]:
    """Build a suppression map for a file, returning None if the file can't be read."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return build_suppression_map(content)
