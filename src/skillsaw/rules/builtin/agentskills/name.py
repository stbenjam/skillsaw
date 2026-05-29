"""AgentSkill name format validation rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, FixOp, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock, FrontmatteredBlock

from ._helpers import NAME_PATTERN, CONSECUTIVE_HYPHENS, _to_kebab, _add_rename


class AgentSkillNameRule(Rule):
    """Validate skill name format per agentskills.io spec"""

    autofix_confidence = AutofixConfidence.SAFE
    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-name"

    @property
    def description(self) -> str:
        return "Skill name must be lowercase with hyphens and match directory name"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                continue
            block = blocks[0]
            if block.frontmatter_error or not block.has_frontmatter:
                continue

            name = block.field_value("name")
            if not name or not isinstance(name, str):
                continue

            name_line = block.key_line("name")

            if not NAME_PATTERN.match(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must contain only lowercase letters, numbers, and hyphens",
                        block=block,
                        line=name_line,
                    )
                )
                continue

            if name.endswith("-"):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not end with a hyphen",
                        block=block,
                        line=name_line,
                    )
                )

            if CONSECUTIVE_HYPHENS.search(name):
                violations.append(
                    self.violation(
                        f"Name '{name}' must not contain consecutive hyphens",
                        block=block,
                        line=name_line,
                    )
                )

            if skill_node.path != context.root_path and name != skill_node.path.name:
                violations.append(
                    self.violation(
                        f"Name '{name}' does not match directory name '{skill_node.path.name}'",
                        block=block,
                        line=name_line,
                    )
                )

        return violations

    def fix(self, context: RepositoryContext, violations: List[RuleViolation]) -> List[FixOp]:
        results: List[FixOp] = []
        for v in violations:
            block = v.block if isinstance(v.block, FrontmatteredBlock) else None
            if block is None or not block.path.exists():
                continue
            original_fm = block.read_frontmatter_text()
            match = re.search(r"^name:\s*(.+)$", original_fm, re.MULTILINE)
            if not match:
                continue
            old_name = match.group(1).strip()
            if "does not match directory" in v.message:
                new_name = block.path.parent.name
            else:
                new_name = _to_kebab(old_name)
            if new_name == old_name or not NAME_PATTERN.match(new_name):
                continue
            fixed_fm = (
                original_fm[: match.start()] + f"name: {new_name}" + original_fm[match.end() :]
            )
            results.append(
                self.frontmatter_fix(
                    block=block,
                    original_fm=original_fm,
                    fixed_fm=fixed_fm,
                    description=f"Renamed '{old_name}' to '{new_name}'",
                    violations=[v],
                )
            )
            _add_rename(context.root_path, old_name, new_name)
        return results
