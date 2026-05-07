"""
Rules for validating skill files
"""

import re
from typing import List

from agentlint.rule import Rule, RuleViolation, Severity
from agentlint.context import RepositoryContext


class SkillFrontmatterRule(Rule):
    """Check that SKILL.md files have frontmatter"""

    @property
    def rule_id(self) -> str:
        return "skill-frontmatter"

    @property
    def description(self) -> str:
        return "SKILL.md files should have frontmatter with name and description"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            skills_dir = plugin_path / "skills"
            if not skills_dir.exists():
                continue

            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    violations.append(self.violation("Missing SKILL.md", file_path=skill_dir))
                    continue

                try:
                    with open(skill_md, "r") as f:
                        content = f.read()
                except IOError as e:
                    violations.append(
                        self.violation(f"Failed to read file: {e}", file_path=skill_md)
                    )
                    continue

                # Check for frontmatter
                if not content.startswith("---"):
                    violations.append(
                        self.violation(
                            "Missing frontmatter (recommended for SKILL.md)", file_path=skill_md
                        )
                    )
                    continue

                # Parse frontmatter
                frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if not frontmatter_match:
                    continue

                frontmatter = frontmatter_match.group(1)

                # Check for recommended fields
                if "name:" not in frontmatter:
                    violations.append(
                        self.violation("Missing 'name' in SKILL.md frontmatter", file_path=skill_md)
                    )

                if "description:" not in frontmatter:
                    violations.append(
                        self.violation(
                            "Missing 'description' in SKILL.md frontmatter", file_path=skill_md
                        )
                    )

        return violations
