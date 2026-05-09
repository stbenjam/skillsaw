"""
Rules for validating agent files
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text


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
                content = read_text(agent_file)
                if content is None:
                    violations.append(
                        self.violation(f"Failed to read file: {agent_file}", file_path=agent_file)
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

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            original = v.file_path.read_text(encoding="utf-8")
            if "Missing frontmatter" in v.message:
                name = v.file_path.stem
                fixed = f"---\nname: {name}\ndescription: \n---\n{original}"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=v.file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Added missing frontmatter to agent file",
                        violations_fixed=[v],
                    )
                )
            elif (
                "Missing 'name'" in v.message or "Missing 'description'" in v.message
            ) and original.startswith("---"):
                fm_match = re.match(r"^---\n(.*?)\n---", original, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    additions = []
                    if "Missing 'name'" in v.message and "name:" not in fm_text:
                        additions.append(f"name: {v.file_path.stem}")
                    if "Missing 'description'" in v.message and "description:" not in fm_text:
                        additions.append("description: ")
                    if additions:
                        insert = "\n".join(additions) + "\n"
                        fixed = original[: fm_match.end()].replace("\n---", f"\n{insert}---", 1)
                        fixed += original[fm_match.end() :]
                        results.append(
                            AutofixResult(
                                rule_id=self.rule_id,
                                file_path=v.file_path,
                                confidence=AutofixConfidence.SAFE,
                                original_content=original,
                                fixed_content=fixed,
                                description="Added missing fields to agent frontmatter",
                                violations_fixed=[v],
                            )
                        )
        return results
