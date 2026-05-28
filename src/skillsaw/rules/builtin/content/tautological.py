"""Content tautological rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    TautologicalDetector,
)


class ContentTautologicalRule(Rule):
    """Detect tautological instructions that waste instruction budget"""

    autofix_confidence = AutofixConfidence.LLM
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

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing AI coding assistant instruction files. Remove "
            "tautological instructions that the AI model already follows "
            "by default (e.g., 'write clean code', 'follow best practices', "
            "'use meaningful variable names').\n\n"
            "Rules:\n"
            "- Remove lines that state something the model does by default\n"
            "- If the line is in a list, remove the list item\n"
            "- If removing leaves an empty section, remove the section heading too\n"
            "- Do NOT remove instructions that add project-specific constraints\n"
            "- Preserve markdown formatting"
        )

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
