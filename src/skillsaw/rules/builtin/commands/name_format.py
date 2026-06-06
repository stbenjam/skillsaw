"""Command name format validation rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import PluginNode
from skillsaw.rules.builtin.utils import read_text, heading_line


class CommandNameFormatRule(Rule):
    """Check that command Name section uses correct format"""

    @property
    def rule_id(self) -> str:
        return "command-name-format"

    @property
    def description(self) -> str:
        return "Command Name section should be 'plugin-name:command-name'"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        from skillsaw.rules.builtin.content_analysis import CommandBlock

        violations = []

        for cmd_block in context.lint_tree.find(CommandBlock):
            cmd_file = cmd_block.path
            parent_plugin = context.lint_tree.find_parent(cmd_block, PluginNode)
            if parent_plugin is None:
                continue
            plugin_name = context.get_plugin_name(parent_plugin.path)
            cmd_name = cmd_file.stem
            expected_name = f"{plugin_name}:{cmd_name}"

            content = read_text(cmd_file)
            if content is None:
                continue

            name_match = re.search(r"^##\s+Name\s*\n+([^\n#]+)", content, re.MULTILINE)
            if name_match:
                name_content = name_match.group(1).strip()
                if expected_name not in name_content:
                    name_line = heading_line(cmd_file, "Name")
                    violations.append(
                        self.violation(
                            f"Name section should contain '{expected_name}', found: '{name_content}'",
                            file_path=cmd_file,
                            line=name_line,
                        )
                    )

        return violations
