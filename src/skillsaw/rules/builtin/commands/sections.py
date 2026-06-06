"""Command sections validation rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text


class CommandSectionsRule(Rule):
    """Check that command files have recommended sections"""

    @property
    def rule_id(self) -> str:
        return "command-sections"

    @property
    def description(self) -> str:
        return "Command files should have Name, Synopsis, Description, and Implementation sections"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        from skillsaw.rules.builtin.content_analysis import CommandBlock

        violations = []

        required_sections = ["Name", "Synopsis", "Description", "Implementation"]

        for cmd_block in context.lint_tree.find(CommandBlock):
            cmd_file = cmd_block.path
            content = read_text(cmd_file)
            if content is None:
                continue

            for section in required_sections:
                pattern = rf"^##\s+{section}\s*$"
                if not re.search(pattern, content, re.MULTILINE):
                    violations.append(
                        self.violation(
                            f"Missing recommended section '## {section}'", file_path=cmd_file
                        )
                    )

        return violations
