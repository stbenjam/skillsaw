import os
from pathlib import Path
from typing import List

from skillsaw import Rule, RuleViolation, Severity, RepositoryContext

sentinel_env = os.environ.get("SKILLSAW_SENTINEL")
if sentinel_env:
    Path(sentinel_env).write_text("custom rule was imported")


class SentinelRule(Rule):
    @property
    def rule_id(self) -> str:
        return "sentinel-rule"

    @property
    def description(self) -> str:
        return "Writes a sentinel file on import to detect unwanted custom-rule loading"

    def default_severity(self) -> Severity:
        return Severity.INFO

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        return []
