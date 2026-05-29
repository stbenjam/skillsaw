"""Command frontmatter validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, FixOp, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.content_analysis import FrontmatteredBlock
from skillsaw.rules.builtin.utils import read_text


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

    def fix(self, context: RepositoryContext, violations: List[RuleViolation]) -> List[FixOp]:
        results: List[FixOp] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            block = v.block if isinstance(v.block, FrontmatteredBlock) else None
            if "Missing frontmatter" in v.message:
                original = read_text(v.file_path)
                if original is None:
                    continue
                results.append(
                    self.file_fix(
                        file_path=v.file_path,
                        original_content=original,
                        fixed_content=f"---\ndescription: \n---\n{original}",
                        description="Added missing frontmatter with description field",
                        violations=[v],
                    )
                )
            elif "Missing 'description'" in v.message and block is not None:
                original_fm = block.read_frontmatter_text()
                fixed_fm = original_fm.rstrip("\n") + "\ndescription: \n"
                results.append(
                    self.frontmatter_fix(
                        block=block,
                        original_fm=original_fm,
                        fixed_fm=fixed_fm,
                        description="Added missing description field to frontmatter",
                        violations=[v],
                    )
                )
        return results
