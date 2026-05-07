"""
Rules for validating agent files
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext


class AgentFrontmatterRule(Rule):
    """Check that agent .md files have valid frontmatter"""

    @property
    def rule_id(self) -> str:
        return "agent-frontmatter"

    @property
    def description(self) -> str:
        return "Agent files must have valid frontmatter with name and description"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for plugin_path in context.plugins:
            agents_dir = plugin_path / "agents"
            if not agents_dir.exists():
                continue

            # Check all .md files in agents directory
            for agent_file in agents_dir.glob("*.md"):
                try:
                    with open(agent_file, "r") as f:
                        content = f.read()
                except IOError as e:
                    violations.append(
                        self.violation(f"Failed to read file: {e}", file_path=agent_file)
                    )
                    continue

                # Check for frontmatter
                if not content.startswith("---"):
                    violations.append(self.violation("Missing frontmatter", file_path=agent_file))
                    continue

                # Parse frontmatter
                frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if not frontmatter_match:
                    violations.append(
                        self.violation("Invalid frontmatter format", file_path=agent_file)
                    )
                    continue

                frontmatter = frontmatter_match.group(1)

                # Check for required fields
                if "name:" not in frontmatter:
                    violations.append(
                        self.violation("Missing 'name' in frontmatter", file_path=agent_file)
                    )

                if "description:" not in frontmatter:
                    violations.append(
                        self.violation("Missing 'description' in frontmatter", file_path=agent_file)
                    )

        return violations
