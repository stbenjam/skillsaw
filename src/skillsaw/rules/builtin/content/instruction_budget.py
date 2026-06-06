"""Content instruction budget rule"""

from typing import List

from skillsaw.rule import AutofixConfidence, Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    InstructionBudgetAnalyzer,
)


class ContentInstructionBudgetRule(Rule):
    """Check total instruction count across all instruction files"""

    autofix_confidence = AutofixConfidence.LLM

    formats = None
    since = "0.7.0"
    baseline_mode = "ceiling"

    @property
    def rule_id(self) -> str:
        return "content-instruction-budget"

    @property
    def description(self) -> str:
        return "Check if instruction count in a file exceeds LLM instruction budget (~150)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are reducing the instruction count in an AI coding assistant "
            "instruction file. The number of imperative instructions in this "
            "file exceeds the recommended budget.\n\n"
            "Rules:\n"
            "- Merge duplicate or near-duplicate instructions\n"
            "- Remove tautological instructions the model follows by default\n"
            "- Consolidate related instructions into fewer, more precise ones\n"
            "- Prefer removing vague instructions over specific ones\n"
            "- Do NOT remove project-specific constraints or requirements\n"
            "- Preserve markdown formatting"
        )

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        content_files = gather_all_content_blocks(context)
        if not content_files:
            return []
        analyzer = InstructionBudgetAnalyzer()
        violations = []
        for cf in content_files:
            budget = analyzer.analyze_file(cf)
            if budget.total_count >= 120:
                sev = Severity.ERROR if budget.over_budget else Severity.WARNING
                msg = (
                    f"Instruction budget: {budget.total_count}/{analyzer.BUDGET} instructions "
                    f"({budget.budget_remaining} remaining)"
                )
                violations.append(
                    self.violation(msg, block=cf, severity=sev, value=budget.total_count)
                )
            elif budget.total_count >= 80:
                msg = (
                    f"Instruction budget: {budget.total_count}/{analyzer.BUDGET} instructions "
                    f"— approaching limit"
                )
                violations.append(
                    self.violation(msg, block=cf, severity=Severity.INFO, value=budget.total_count)
                )
        return violations
