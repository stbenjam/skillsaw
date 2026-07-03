"""Plugin fixture whose rule's rule_id property raises.

Regression fixture: a plugin-controlled ``rule_id`` property that raises
must surface as a ``plugin-load-error`` violation, never as an unhandled
traceback that aborts the lint.
"""

from typing import List

from skillsaw import RepositoryContext, Rule, RuleViolation, Severity


class RaisingIdRule(Rule):
    """A rule whose rule_id property raises when accessed."""

    @property
    def rule_id(self) -> str:
        raise RuntimeError("rule_id exploded (fixture)")

    @property
    def description(self) -> str:
        return "Rule with a raising rule_id property (fixture)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []


SKILLSAW_RULES = [RaisingIdRule]
