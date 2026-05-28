"""
Rule: instruction-file-valid
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.rules.builtin.content_analysis import InstructionBlock
from skillsaw.rules.builtin.utils import read_text

from ._helpers import INSTRUCTION_FILES


class InstructionFileValidRule(Rule):
    """Check that instruction files are valid UTF-8 and non-empty"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-file-valid"

    @property
    def description(self) -> str:
        return "Instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) must be valid and non-empty"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for block in context.lint_tree.find(InstructionBlock):
            if block.path.name not in INSTRUCTION_FILES:
                continue

            content = read_text(block.path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read {block.path.name} (invalid encoding or I/O error)",
                        file_path=block.path,
                    )
                )
                continue

            if not content.strip():
                violations.append(
                    self.violation(f"{block.path.name} is empty", file_path=block.path)
                )

        return violations
