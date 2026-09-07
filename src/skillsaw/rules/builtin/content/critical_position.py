"""Content critical position rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    CriticalPositionAnalyzer,
)


class ContentCriticalPositionRule(Rule):
    """Detect critical instructions buried in the attention dead zone"""

    since = "0.7.0"
    # The lost-in-the-middle dip is real, but it is a property of a long
    # context window, not of one skill file loaded on its own. The middle of
    # a single file is not the middle of the context, so the rule's position
    # heuristic never measured the thing the research describes.
    deprecated = "0.18.0"
    deprecated_reason = (
        "Built on the lost-in-the-middle attention research: instructions in "
        "the middle 20–80% of a long file were assumed to be the most likely "
        "to be dropped. Models still show that attention dip, but it occurs "
        "across a long context window, not within a single skill or "
        "instruction file loaded on its own. Where a line sits inside one "
        "file says little about where it lands in the context, so moving "
        "CRITICAL lines to the edges of a file was not worth the churn."
    )

    _DEFAULT_MIN_LINES = 50

    config_schema = {
        "min-lines": {
            "type": "int",
            "default": 50,
            "description": "Minimum file length (in lines) before the rule activates",
        },
    }

    @property
    def rule_id(self) -> str:
        return "content-critical-position"

    @property
    def description(self) -> str:
        return "Detect critical instructions in the middle of files where LLM attention is lowest"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        min_lines = self.config.get("min-lines", self._DEFAULT_MIN_LINES)
        analyzer = CriticalPositionAnalyzer(min_lines=min_lines)
        for cf in gather_all_content_blocks(context):
            for issue in analyzer.analyze(cf):
                violations.append(
                    self.violation(
                        f"'{issue.keyword}' instruction at line {issue.line} is in the attention dead zone (20-80%) — {issue.suggested_position}",
                        block=cf,
                        line=issue.line,
                    )
                )
        return violations
