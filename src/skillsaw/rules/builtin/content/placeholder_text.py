"""Content placeholder text rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentPlaceholderTextRule(Rule):
    """Detect TODO markers, bracket placeholders, and unfilled template text"""

    formats = None
    since = "0.9.0"
    repo_types = None

    _PLACEHOLDER_PATTERNS = [
        (re.compile(r"\bTODO\b"), "TODO marker"),
        (re.compile(r"\bFIXME\b"), "FIXME marker"),
        (re.compile(r"\bXXX\b"), "XXX marker"),
        (re.compile(r"\[link\s+here\]", re.IGNORECASE), "Placeholder link"),
        (re.compile(r"\[Insert\s+[^\]]+\]", re.IGNORECASE), "Insert placeholder"),
        (re.compile(r"\[If\s+[^\]]+\]", re.IGNORECASE), "Conditional placeholder"),
        (
            re.compile(
                r"\*(?:TBD|to be added|details to be added|content to be added)\*",
                re.IGNORECASE,
            ),
            "Unfilled template text",
        ),
    ]

    @property
    def rule_id(self) -> str:
        return "content-placeholder-text"

    @property
    def description(self) -> str:
        return "Detect TODO markers, bracket placeholders, and unfilled template text"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body(strip_code_blocks=True)
            if not body:
                continue
            for line_num, line in enumerate(body.splitlines(), 1):
                if not line.strip():
                    continue
                for pattern, desc in self._PLACEHOLDER_PATTERNS:
                    match = pattern.search(line)
                    if match:
                        violations.append(
                            self.violation(
                                f"Placeholder text ({desc}): '{match.group()}'",
                                block=cf,
                                line=line_num,
                            )
                        )
        return violations
