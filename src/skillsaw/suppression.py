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

Multi-line HTML comments are fully supported::

    <!--
        skillsaw-disable rule-id
    -->
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set

# Directive patterns applied to the *text inside* an HTML comment.
# These match the full comment body, allowing arbitrary whitespace/newlines.
_DISABLE_NEXT_LINE_DIR = re.compile(
    r"skillsaw-disable-next-line\s+([\w,\s-]+)",
    re.IGNORECASE,
)
_DISABLE_DIR = re.compile(
    r"skillsaw-disable(?!-next-line)\s*([\w,\s-]*)",
    re.IGNORECASE,
)
_ENABLE_DIR = re.compile(
    r"skillsaw-enable\s*([\w,\s-]*)",
    re.IGNORECASE,
)


def _parse_rule_ids(raw: str) -> List[str]:
    """Parse comma-separated rule IDs from a directive."""
    return [rid.strip() for rid in raw.split(",") if rid.strip()]


# ------------------------------------------------------------------
# Directive extraction via HTMLParser
# ------------------------------------------------------------------


@dataclass
class _Directive:
    """A parsed suppression directive with its location."""

    kind: str  # "disable", "enable", or "disable-next-line"
    rule_ids: List[str]  # empty list means "all rules"
    line: int  # 1-based line number where the comment starts (``<!--``)


class _CommentParser(HTMLParser):
    """HTMLParser subclass that extracts skillsaw directives from HTML comments.

    Using HTMLParser instead of hand-rolled regex gives us correct handling of
    multi-line comments, comments with extra whitespace, and other edge cases.
    """

    def __init__(self) -> None:
        super().__init__()
        self.directives: List[_Directive] = []

    def handle_comment(self, data: str) -> None:
        line, _col = self.getpos()
        # Normalise the comment text: collapse whitespace so that multi-line
        # comments like ``<!--\n  skillsaw-enable\n  some-rule -->`` become a
        # single logical string we can match against.
        text = " ".join(data.split())

        m = _DISABLE_NEXT_LINE_DIR.search(text)
        if m:
            self.directives.append(
                _Directive("disable-next-line", _parse_rule_ids(m.group(1)), line)
            )
            return

        m = _DISABLE_DIR.search(text)
        if m:
            self.directives.append(_Directive("disable", _parse_rule_ids(m.group(1).strip()), line))
            return

        m = _ENABLE_DIR.search(text)
        if m:
            self.directives.append(_Directive("enable", _parse_rule_ids(m.group(1).strip()), line))
            return


def _extract_directives(content: str) -> List[_Directive]:
    """Extract all skillsaw directives from *content* using HTMLParser.

    HTMLParser.getpos() returns the line where the parser currently sits, which
    for comments corresponds to the line of the opening ``<!--``.
    """
    parser = _CommentParser()
    parser.feed(content)
    return parser.directives


# ------------------------------------------------------------------
# SuppressionMap
# ------------------------------------------------------------------


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
    total_lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    if content.endswith("\n"):
        total_lines = content.count("\n")
    else:
        total_lines = content.count("\n") + 1

    # --- Step 1: extract directives (handles multi-line comments) ----------
    directives = _extract_directives(content)

    # Build a map of line -> list of directives that start on that line.
    # ``_Directive.line`` is 1-based from HTMLParser.getpos().
    directive_at: Dict[int, List[_Directive]] = {}
    for d in directives:
        directive_at.setdefault(d.line, []).append(d)

    # Build a set of lines that are part of directive comments (so we don't
    # apply suppressions to the directive lines themselves for disable/enable).
    # For ``disable-next-line`` the directive line should be skipped and the
    # suppression applied to the *next non-directive* line.
    # We need the raw comment spans to know which lines are directive lines.
    directive_comment_lines: Set[int] = set()
    for d in directives:
        # Walk the content to find the closing ``-->`` for this comment.
        # We know ``d.line`` is where ``<!--`` starts.
        _mark_comment_lines(content, d.line, directive_comment_lines)

    # --- Step 2: walk lines and apply suppressions -------------------------
    disabled: Set[str] = set()
    disable_all_active: bool = False

    suppressed_lines: Dict[int, Set[str]] = {}
    fully_suppressed_lines: Set[int] = set()

    next_line_rules: Optional[List[str]] = None

    for line_num_0 in range(total_lines):
        content_line = line_num_0 + 1  # 1-based within the content
        file_line = content_line + line_offset

        # Process directives that start on this content line
        line_directives = directive_at.get(content_line, [])
        for d in line_directives:
            if d.kind == "disable-next-line":
                next_line_rules = d.rule_ids
            elif d.kind == "disable":
                if d.rule_ids:
                    disabled.update(d.rule_ids)
                else:
                    disable_all_active = True
            elif d.kind == "enable":
                if d.rule_ids:
                    for rid in d.rule_ids:
                        disabled.discard(rid)
                else:
                    disabled.clear()
                    disable_all_active = False

        # Skip directive comment lines — don't apply suppression to them
        if content_line in directive_comment_lines:
            # But if next_line_rules was set by a *previous* directive and
            # this line is itself a directive, carry it forward.
            continue

        # Apply next-line suppression
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


def _mark_comment_lines(content: str, start_line: int, out: Set[int]) -> None:
    """Add all line numbers spanned by an HTML comment starting at *start_line*.

    We scan from the beginning of *start_line* forward until we find ``-->``.
    """
    lines = content.splitlines()
    for i in range(start_line - 1, len(lines)):
        out.add(i + 1)  # 1-based
        if "-->" in lines[i]:
            # Check that the ``-->`` comes after the ``<!--`` on the same line,
            # or is simply present on a subsequent line.
            if i == start_line - 1:
                # Same line: only count if ``-->`` comes after ``<!--``
                idx_open = lines[i].find("<!--")
                idx_close = lines[i].find("-->", idx_open + 4 if idx_open >= 0 else 0)
                if idx_close >= 0:
                    break
            else:
                break


def build_suppression_map_for_file(file_path: Path) -> Optional[SuppressionMap]:
    """Build a suppression map for a file, returning None if the file can't be read."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    return build_suppression_map(content)
