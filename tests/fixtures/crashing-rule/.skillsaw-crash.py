from typing import List

from skillsaw import Rule, RuleViolation, Severity, RepositoryContext


class CrashingRule(Rule):
    @property
    def rule_id(self) -> str:
        return "fixture-crashing-rule"

    @property
    def description(self) -> str:
        return "Always raises to exercise rule-crash handling"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        raise RuntimeError("intentional crash")
