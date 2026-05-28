"""Content weak language rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    SkillRefBlock,
    WeakLanguageDetector,
)


class ContentWeakLanguageRule(Rule):
    """Detect hedging, vague, and non-actionable language in instruction files"""

    autofix_confidence = AutofixConfidence.LLM
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

    @property
    def llm_fix_prompt(self):
        return (
            "You are a technical writing assistant fixing AI coding assistant "
            "instruction files. Your job is to replace weak, hedging language "
            "with direct, actionable instructions.\n\n"
            "Rules:\n"
            "- Replace 'try to X' with 'X'\n"
            "- Replace 'consider doing X' with 'do X' or remove the line\n"
            "- Replace 'if possible' with explicit conditions\n"
            "- Replace vague adverbs (properly, correctly, appropriately) "
            "with specific behavior\n"
            "- Do NOT change the meaning or intent of the instruction\n"
            "- Do NOT add new instructions\n"
            "- Preserve markdown formatting"
        )

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
