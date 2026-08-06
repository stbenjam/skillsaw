"""Content cognitive chunks rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
)


class ContentCognitiveChunksRule(Rule):
    """Check section organization for cognitive chunking"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-cognitive-chunks"

    @property
    def description(self) -> str:
        return "Check that instruction files are organized into cognitive chunks with headings"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for cf in gather_all_content_blocks(context):
            body = cf.read_body()
            if not body or len(body.strip()) < 100:
                continue
            lines = body.splitlines()
            headings = cf.markdown.headings()

            if not headings and len(lines) > 10:
                violations.append(
                    self.violation(
                        "No headings in instruction file — add section headings for cognitive chunking",
                        block=cf,
                    )
                )
                continue

            if len(headings) == 1 and len(lines) > 30:
                violations.append(
                    self.violation(
                        "All content under a single heading — break into task-organized sections",
                        block=cf,
                    )
                )
        return violations
