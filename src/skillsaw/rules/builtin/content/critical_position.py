"""Content critical position rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    CriticalPositionAnalyzer,
)


class ContentCriticalPositionRule(Rule):
    """Detect critical instructions buried in the attention dead zone"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"

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
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are reorganizing AI coding assistant instruction files to "
            "improve LLM attention. Critical instructions (IMPORTANT, MUST, "
            "NEVER, ALWAYS, CRITICAL, WARNING, REQUIRED) should be in the "
            "first 20% or last 20% of the file.\n\n"
            "Rules:\n"
            "- Move flagged critical instructions to the top or bottom of the file\n"
            "- Prefer moving to the top when the instruction is a constraint\n"
            "- Prefer moving to the bottom when it's a reminder or checklist item\n"
            "- Preserve section structure — move the whole section if needed\n"
            "- Do NOT change the content of the instructions\n"
            "- Preserve markdown formatting"
        )

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
