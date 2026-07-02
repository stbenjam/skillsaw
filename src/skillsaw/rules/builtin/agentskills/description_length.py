"""AgentSkill description length budget rule.

Skill descriptions are permanent context: they are loaded into every
prompt so the agent can decide which skill to route to.  Every character
in a description is therefore paid on every single request, and some
ecosystems rank or route on only a prefix of the description — overly
long descriptions have been claimed to be truncated by some routers.

The agentskills.io spec's hard 1024-character limit is enforced
separately by ``agentskill-description`` (spec parity).  This rule is
an *opinionated, configurable soft budget* kept deliberately separate:
users who disagree with the budget can tune or disable it without
losing spec validation.
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock


class AgentSkillDescriptionLengthRule(Rule):
    """Soft budget on skill description length (opt-in)"""

    since = "0.15.0"

    # Opinionated quality rule — must never fire on existing codebases
    # until users explicitly enable it.
    default_enabled = False

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    DEFAULT_MAX_LENGTH = 256

    config_schema = {
        "max_length": {
            "type": "int",
            "default": DEFAULT_MAX_LENGTH,
            "description": "Soft budget for description length in characters",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-description-length"

    @property
    def description(self) -> str:
        max_length = self.config.get("max_length", self.DEFAULT_MAX_LENGTH)
        return f"Skill description should stay within a soft budget of {max_length} characters (opt-in)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        max_length = self.config.get("max_length", self.DEFAULT_MAX_LENGTH)
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            blocks = skill_node.find(SkillBlock)
            if not blocks:
                continue
            block = blocks[0]
            if block.frontmatter_error or not block.has_frontmatter:
                continue

            # Missing / non-string / empty descriptions are other rules'
            # job (agentskill-valid, agentskill-description).
            desc = block.field_value("description")
            if not desc or not isinstance(desc, str):
                continue

            length = len(desc.strip())
            if length > max_length:
                violations.append(
                    self.violation(
                        f"Description is {length} characters "
                        f"(soft budget: {max_length}) — descriptions are loaded "
                        f"into every prompt for skill routing",
                        block=block,
                        line=block.key_line("description"),
                    )
                )

        return violations
