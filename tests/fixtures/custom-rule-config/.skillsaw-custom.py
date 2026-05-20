from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from typing import List


class RepoRootRule(Rule):
    @property
    def rule_id(self) -> str:
        return "repo-root-rule"

    @property
    def description(self) -> str:
        return "Custom rule that lives next to the config at the repo root"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return [self.violation("fired from repo root rule")]
