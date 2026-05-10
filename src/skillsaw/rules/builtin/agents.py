"""
Rules for validating agent files
"""

import re
from collections import defaultdict
from pathlib import Path
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
                if not re.search(r"^name\s*:", frontmatter, re.MULTILINE):
                    violations.append(
                        self.violation("Missing 'name' in frontmatter", file_path=agent_file)
                    )

                if not re.search(r"^description\s*:", frontmatter, re.MULTILINE):
                    violations.append(
                        self.violation("Missing 'description' in frontmatter", file_path=agent_file)
                    )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []

        # Group violations by file path so we can apply all fixes for the same
        # file in a single AutofixResult, avoiding conflicts when multiple
        # fields are missing.
        by_file: defaultdict[Path, List[RuleViolation]] = defaultdict(list)
        for v in violations:
            if v.file_path:
                by_file[v.file_path].append(v)

        for file_path, file_violations in by_file.items():
            if not file_path.exists():
                continue

            original = read_text(file_path)
            if original is None:
                continue
            messages = {v.message for v in file_violations}

            # Case 1: Missing frontmatter block entirely
            if any("Missing frontmatter" in m for m in messages):
                name = file_path.stem
                fixed = f"---\nname: {name}\ndescription: \n---\n{original}"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Added missing frontmatter to agent file",
                        violations_fixed=file_violations,
                    )
                )
                continue

            # Case 2: Frontmatter exists but fields are missing — collect all
            # missing fields and produce one combined fix.
            missing_name = any("Missing 'name'" in m for m in messages)
            missing_desc = any("Missing 'description'" in m for m in messages)
            if (missing_name or missing_desc) and original.startswith("---"):
                fm_match = re.match(r"^---\n(.*?)\n---", original, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    additions = []
                    if missing_name and not re.search(
                        r"^name\s*:", fm_text, re.MULTILINE
                    ):
                        additions.append(f"name: {file_path.stem}")
                    if missing_desc and not re.search(
                        r"^description\s*:", fm_text, re.MULTILINE
                    ):
                        additions.append("description: ")
                    if additions:
                        insert = "\n".join(additions) + "\n"
                        fixed = original[: fm_match.end()].replace("\n---", f"\n{insert}---", 1)
                        fixed += original[fm_match.end() :]
                        results.append(
                            AutofixResult(
                                rule_id=self.rule_id,
                                file_path=file_path,
                                confidence=AutofixConfidence.SAFE,
                                original_content=original,
                                fixed_content=fixed,
                                description="Added missing fields to agent frontmatter",
                                violations_fixed=file_violations,
                            )
                        )
        return results
