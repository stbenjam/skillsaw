"""Command frontmatter validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import insert_frontmatter_fields


class CommandFrontmatterRule(Rule):
    """Check that command files have valid frontmatter"""

    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "command-frontmatter"

    @property
    def description(self) -> str:
        return "Command files must have valid frontmatter with description"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        from skillsaw.rules.builtin.content_analysis import CommandBlock

        violations = []

        for block in context.lint_tree.find(CommandBlock):
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        block=block,
                        line=block.frontmatter_error_line,
                    )
                )
                continue

            if not block.has_frontmatter:
                violations.append(self.violation("Missing frontmatter", block=block))
                continue

            if not block.field("description"):
                violations.append(
                    self.violation("Missing 'description' in frontmatter", block=block)
                )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            original = v.file_path.read_text(encoding="utf-8")
            if "Missing frontmatter" in v.message:
                fixed = f"---\ndescription: \n---\n{original}"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Added missing frontmatter with description field",
                        violations_fixed=[v],
                    )
                )
            elif "Missing 'description'" in v.message and original.startswith("---"):
                fixed = insert_frontmatter_fields(original, ["description: "])
                if fixed is not None:
                    results.append(
                        AutofixResult(
                            rule_id=self.rule_id,
                            file_path=v.file_path,
                            confidence=AutofixConfidence.SAFE,
                            original_content=original,
                            fixed_content=fixed,
                            description="Added missing description field to frontmatter",
                            violations_fixed=[v],
                        )
                    )
        return results
