"""
Rules for validating command file format
"""

import re
from pathlib import Path
from typing import List

from agentlint.rule import Rule, RuleViolation, Severity
from agentlint.context import RepositoryContext


class CommandNamingRule(Rule):
    """Check that command files use kebab-case naming"""

    @property
    def rule_id(self) -> str:
        return "command-naming"

    @property
    def description(self) -> str:
        return "Command files should use kebab-case naming"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                continue

            for cmd_file in commands_dir.glob("*.md"):
                cmd_name = cmd_file.stem
                if not self._is_kebab_case(cmd_name):
                    violations.append(
                        self.violation(
                            f"Command name '{cmd_name}' should use kebab-case", file_path=cmd_file
                        )
                    )

        return violations

    @staticmethod
    def _is_kebab_case(name: str) -> bool:
        return bool(re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name))


class CommandFrontmatterRule(Rule):
    """Check that command files have valid frontmatter"""

    @property
    def rule_id(self) -> str:
        return "command-frontmatter"

    @property
    def description(self) -> str:
        return "Command files must have valid frontmatter with description"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                continue

            for cmd_file in commands_dir.glob("*.md"):
                try:
                    with open(cmd_file, "r") as f:
                        content = f.read()
                except IOError as e:
                    violations.append(
                        self.violation(f"Failed to read file: {e}", file_path=cmd_file)
                    )
                    continue

                # Check for frontmatter
                if not content.startswith("---"):
                    violations.append(self.violation("Missing frontmatter", file_path=cmd_file))
                    continue

                # Parse frontmatter
                frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if not frontmatter_match:
                    violations.append(
                        self.violation("Invalid frontmatter format", file_path=cmd_file)
                    )
                    continue

                frontmatter = frontmatter_match.group(1)

                # Check for required fields
                if "description:" not in frontmatter:
                    violations.append(
                        self.violation("Missing 'description' in frontmatter", file_path=cmd_file)
                    )

        return violations


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
        violations = []

        required_sections = ["Name", "Synopsis", "Description", "Implementation"]

        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                continue

            for cmd_file in commands_dir.glob("*.md"):
                try:
                    with open(cmd_file, "r") as f:
                        content = f.read()
                except IOError:
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
        violations = []

        for plugin_path in context.plugins:
            plugin_name = context.get_plugin_name(plugin_path)
            commands_dir = plugin_path / "commands"

            if not commands_dir.exists():
                continue

            for cmd_file in commands_dir.glob("*.md"):
                cmd_name = cmd_file.stem
                expected_name = f"{plugin_name}:{cmd_name}"

                try:
                    with open(cmd_file, "r") as f:
                        content = f.read()
                except IOError:
                    continue

                # Find Name section
                name_match = re.search(r"^##\s+Name\s*\n+([^\n#]+)", content, re.MULTILINE)
                if name_match:
                    name_content = name_match.group(1).strip()
                    if expected_name not in name_content:
                        violations.append(
                            self.violation(
                                f"Name section should contain '{expected_name}', found: '{name_content}'",
                                file_path=cmd_file,
                            )
                        )

        return violations
