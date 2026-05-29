"""
Rule for validating skill file frontmatter
"""

from collections import defaultdict
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, FixOp, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock, FrontmatteredBlock
from skillsaw.rules.builtin.utils import read_text


class SkillFrontmatterRule(Rule):
    """Check that SKILL.md files have frontmatter"""

    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "skill-frontmatter"

    @property
    def description(self) -> str:
        return "SKILL.md files should have frontmatter with name and description"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    @property
    def llm_fix_prompt(self):
        return (
            "You are fixing YAML frontmatter for a SKILL.md file.\n\n"
            "The block you are editing is the raw YAML between the --- delimiters.\n"
            "Do NOT include the --- delimiters in your output.\n\n"
            "Rules:\n"
            "- Must have 'name' and 'description' fields\n"
            "- 'name' should be the skill directory name\n"
            "- 'description' should be imperative and tell the model when to invoke it, "
            "e.g. 'Use when the user asks to deploy a service' — "
            "derive it from the body content, keep it under 200 tokens\n"
            "- If the YAML is malformed, fix the syntax\n"
            "- Preserve any other existing frontmatter fields"
        )

    @property
    def llm_fix_frontmatter(self) -> bool:
        return True

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                violations.append(self.violation("Missing SKILL.md", file_path=skill_node.path))
                continue

            block = blocks[0]
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        file_path=block.path,
                        line=block.frontmatter_error_line,
                        block=block,
                    )
                )
                continue

            if not block.has_frontmatter:
                violations.append(
                    self.violation(
                        "Missing frontmatter (recommended for SKILL.md)",
                        file_path=block.path,
                        block=block,
                    )
                )
                continue

            if not block.field("name"):
                violations.append(
                    self.violation(
                        "Missing 'name' in SKILL.md frontmatter",
                        file_path=block.path,
                        block=block,
                    )
                )

            if not block.field("description"):
                violations.append(
                    self.violation(
                        "Missing 'description' in SKILL.md frontmatter",
                        file_path=block.path,
                        block=block,
                    )
                )

        return violations

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[FixOp]:
        results: List[FixOp] = []

        by_file: defaultdict[Path, List[RuleViolation]] = defaultdict(list)
        for v in violations:
            if v.file_path:
                by_file[v.file_path].append(v)

        for file_path, file_violations in by_file.items():
            messages = {v.message for v in file_violations}

            if any("Missing SKILL.md" in m for m in messages):
                skill_md = file_path / "SKILL.md"
                name = file_path.name
                results.append(self.file_fix(
                    file_path=skill_md,
                    original_content="",
                    fixed_content=f"---\nname: {name}\ndescription: \n---\n",
                    description=f"Created SKILL.md with frontmatter for {name}",
                    violations=file_violations,
                ))
                continue

            if not file_path.exists():
                continue

            block = next(
                (v.block for v in file_violations if isinstance(v.block, FrontmatteredBlock)),
                None,
            )

            if any("Missing frontmatter" in m for m in messages):
                original = read_text(file_path)
                if original is None:
                    continue
                name = file_path.parent.name
                results.append(self.file_fix(
                    file_path=file_path,
                    original_content=original,
                    fixed_content=f"---\nname: {name}\ndescription: \n---\n{original}",
                    description="Added missing frontmatter to SKILL.md",
                    violations=file_violations,
                ))
                continue

            if block is None:
                continue
            missing_name = any("Missing 'name'" in m for m in messages)
            missing_desc = any("Missing 'description'" in m for m in messages)
            if missing_name or missing_desc:
                original_fm = block.read_frontmatter_text()
                additions = []
                if missing_name and "name:" not in original_fm:
                    additions.append(f"name: {file_path.parent.name}")
                if missing_desc and "description:" not in original_fm:
                    additions.append("description: ")
                if additions:
                    fixed_fm = original_fm.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
                    results.append(self.frontmatter_fix(
                        block=block,
                        original_fm=original_fm,
                        fixed_fm=fixed_fm,
                        description="Added missing fields to SKILL.md frontmatter",
                        violations=file_violations,
                    ))
        return results
