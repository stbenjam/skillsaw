"""AgentSkill description validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock

from ._helpers import DESCRIPTION_MAX_LENGTH


class AgentSkillDescriptionRule(Rule):
    """Validate skill description quality"""

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-description"

    @property
    def description(self) -> str:
        return "Skill description should be meaningful and within length limits"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                continue
            block = blocks[0]
            if block.frontmatter_error or not block.has_frontmatter:
                continue

            desc = block.field_value("description")
            if not desc or not isinstance(desc, str):
                continue

            desc_line = block.key_line("description")
            stripped = desc.strip()
            if not stripped:
                violations.append(
                    self.violation(
                        "Description is empty or whitespace-only",
                        file_path=block.path,
                        line=desc_line,
                    )
                )
                continue

            if len(stripped) > DESCRIPTION_MAX_LENGTH:
                violations.append(
                    self.violation(
                        f"Description exceeds {DESCRIPTION_MAX_LENGTH} characters ({len(stripped)})",
                        file_path=block.path,
                        line=desc_line,
                    )
                )

        return violations
