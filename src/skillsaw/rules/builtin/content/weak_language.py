"""Content weak language rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    SkillRefBlock,
    WeakLanguageDetector,
)


class ContentWeakLanguageRule(Rule):
    """Detect hedging, vague, and non-actionable language in instruction files"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-weak-language"

    @property
    def description(self) -> str:
        return "Detect hedging, vague, and non-actionable language in instruction files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    _REFERENCE_BLOCK_TYPES = (SkillRefBlock,)

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = WeakLanguageDetector()
        for cf in gather_all_content_blocks(context):
            is_reference = isinstance(cf, self._REFERENCE_BLOCK_TYPES)
            for match in detector.analyze(cf):
                violations.append(
                    self.violation(
                        f"Weak language ({match.category}): '{match.phrase}' — {match.suggested_fix}",
                        block=cf,
                        line=match.line,
                        severity=Severity.INFO if is_reference else None,
                    )
                )
        return violations
