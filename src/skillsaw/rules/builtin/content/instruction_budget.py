"""Content instruction budget rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    InstructionBudgetAnalyzer,
)


class ContentInstructionBudgetRule(Rule):
    """Check total instruction count across all instruction files"""

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
