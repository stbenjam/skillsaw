"""Content redundant with tooling rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import (
    gather_all_content_blocks,
    RedundancyDetector,
)


class ContentRedundantWithToolingRule(Rule):
    """Detect instructions that duplicate existing tooling configuration"""

    formats = None
    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "content-redundant-with-tooling"

    @property
    def description(self) -> str:
        return "Detect instructions that duplicate .editorconfig, ESLint, Prettier, or tsconfig settings"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        detector = RedundancyDetector()
        for cf in gather_all_content_blocks(context):
            for match in detector.analyze(cf, context.root_path):
                violations.append(
                    self.violation(
                        f"Redundant with {match.existing_config_file} ({match.config_value}): '{match.instruction}'",
                        block=cf,
                        line=match.line,
                    )
                )
        return violations
