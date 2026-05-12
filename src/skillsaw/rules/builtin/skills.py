"""
Rules for validating skill files
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixResult, AutofixConfidence
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock
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
                    self.violation(block.frontmatter_error, file_path=block.path, block=block)
                )
                continue

            if block.frontmatter is None:
                violations.append(
                    self.violation(
                        "Missing frontmatter (recommended for SKILL.md)",
                        file_path=block.path,
                        block=block,
                    )
                )
                continue

            if "name" not in block.frontmatter:
                violations.append(
                    self.violation(
                        "Missing 'name' in SKILL.md frontmatter",
                        file_path=block.path,
                        block=block,
                    )
                )

            if "description" not in block.frontmatter:
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
            messages = {v.message for v in file_violations}

            # Case 1: Missing SKILL.md entirely — file_path is the directory
            if any("Missing SKILL.md" in m for m in messages):
                skill_md = file_path / "SKILL.md"
                name = file_path.name
                fixed = f"---\nname: {name}\ndescription: \n---\n"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=skill_md,
                        confidence=AutofixConfidence.SAFE,
                        original_content="",
                        fixed_content=fixed,
                        description=f"Created SKILL.md with frontmatter for {name}",
                        violations_fixed=file_violations,
                    )
                )
                continue

            if not file_path.exists():
                continue

            original = read_text(file_path)
            if original is None:
                continue

            # Case 2: Missing frontmatter block entirely
            if any("Missing frontmatter" in m for m in messages):
                name = file_path.parent.name
                fixed = f"---\nname: {name}\ndescription: \n---\n{original}"
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=file_path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Added missing frontmatter to SKILL.md",
                        violations_fixed=file_violations,
                    )
                )
                continue

            # Case 3: Frontmatter exists but fields are missing — collect all
            # missing fields and produce one combined fix.
            missing_name = any("Missing 'name'" in m for m in messages)
            missing_desc = any("Missing 'description'" in m for m in messages)
            if (missing_name or missing_desc) and original.startswith("---"):
                fm_match = re.match(r"^---\r?\n(.*?)\r?\n---", original, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    additions = []
                    if missing_name and "name:" not in fm_text:
                        additions.append(f"name: {file_path.parent.name}")
                    if missing_desc and "description:" not in fm_text:
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
                                description="Added missing fields to SKILL.md frontmatter",
                                violations_fixed=file_violations,
                            )
                        )
        return results
