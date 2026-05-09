"""
Rules for validating skill files
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text


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

                content = read_text(skill_md)
                if content is None:
                    violations.append(
                        self.violation(f"Failed to read file: {skill_md}", file_path=skill_md)
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

    def fix(self, context: RepositoryContext, violations: List[RuleViolation]) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path:
                continue
            if "Missing SKILL.md" in v.message:
                skill_md = v.file_path / "SKILL.md"
                name = v.file_path.name
                fixed = f"---\nname: {name}\ndescription: \n---\n"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=skill_md,
                        confidence=AutofixConfidence.SAFE,
                        original_content="",
                        fixed_content=fixed,
                        description=f"Created SKILL.md with frontmatter for {name}",
                        violations_fixed=[v],
                    )
                )
            elif v.file_path.exists():
                original = v.file_path.read_text(encoding="utf-8")
                if "Missing frontmatter" in v.message:
                    name = v.file_path.parent.name
                    fixed = f"---\nname: {name}\ndescription: \n---\n{original}"
                    results.append(
                        AutofixResult(
                            rule_id=self.rule_id,
                            file_path=v.file_path,
                            confidence=AutofixConfidence.SAFE,
                            original_content=original,
                            fixed_content=fixed,
                            description="Added missing frontmatter to SKILL.md",
                            violations_fixed=[v],
                        )
                    )
                elif ("Missing 'name'" in v.message or "Missing 'description'" in v.message) and original.startswith("---"):
                    fm_match = re.match(r"^---\n(.*?)\n---", original, re.DOTALL)
                    if fm_match:
                        fm_text = fm_match.group(1)
                        additions = []
                        if "Missing 'name'" in v.message and "name:" not in fm_text:
                            additions.append(f"name: {v.file_path.parent.name}")
                        if "Missing 'description'" in v.message and "description:" not in fm_text:
                            additions.append("description: ")
                        if additions:
                            insert = "\n".join(additions) + "\n"
                            fixed = original[:fm_match.end()].replace("\n---", f"\n{insert}---", 1)
                            fixed += original[fm_match.end():]
                            results.append(
                                AutofixResult(
                                    rule_id=self.rule_id,
                                    file_path=v.file_path,
                                    confidence=AutofixConfidence.SAFE,
                                    original_content=original,
                                    fixed_content=fixed,
                                    description="Added missing fields to SKILL.md frontmatter",
                                    violations_fixed=[v],
                                )
                            )
        return results
