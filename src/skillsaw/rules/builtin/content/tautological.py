"""Content tautological rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    TautologicalDetector,
)


class ContentTautologicalRule(Rule):
    """Detect tautological instructions that waste instruction budget"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-tautological"

    @property
    def description(self) -> str:
        return "Detect tautological instructions that the model already follows by default"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = TautologicalDetector()
        for cf in gather_all_content_blocks(context):
            for match in detector.analyze(cf):
                violations.append(
                    self.violation(
                        f"Tautological: '{match.phrase}' — {match.reason}",
                        block=cf,
                        line=match.line,
                    )
                )
        return violations
