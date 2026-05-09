"""
Rules for validating command file format
"""

import re
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text, heading_line


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
                content = read_text(cmd_file)
                if content is None:
                    violations.append(
                        self.violation(f"Failed to read file: {cmd_file}", file_path=cmd_file)
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
                fm_match = re.match(r"^---\n(.*?)\n---", original, re.DOTALL)
                if fm_match:
                    fm_end = fm_match.end()
                    fixed = original[:fm_end].replace("\n---", "\ndescription: \n---", 1)
                    fixed += original[fm_end:]
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

                content = read_text(cmd_file)
                if content is None:
                    continue

                # Find Name section
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
