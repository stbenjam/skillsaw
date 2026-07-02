"""AgentSkill description validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock

from ._helpers import DESCRIPTION_MAX_LENGTH


class AgentSkillDescriptionRule(Rule):
    """Validate skill description quality.

    The length limit defaults to the agentskills.io spec's 1024
    characters, and is configurable via ``max_length``. A tighter
    budget such as ``max_length: 256`` is recommended: descriptions
    are permanent context loaded into every prompt for skill routing,
    so every character is paid on every request, and some ecosystems
    rank or route on only a prefix of the description. Values above
    1024 are honored as configured — the spec limit itself is
    validated by the ecosystem at publish time.
    """

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }

    config_schema = {
        "max_length": {
            "type": "int",
            "default": DESCRIPTION_MAX_LENGTH,
            "description": "Maximum description length in characters (spec limit 1024; consider 256 to keep routing context lean)",
        },
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
        # Fall back to the spec limit when the configured value isn't a
        # positive integer (a blank key parses as None; bool is an int
        # subclass — reject it) so a bad config can't crash the lint.
        max_length = self.config.get("max_length")
        if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length <= 0:
            max_length = DESCRIPTION_MAX_LENGTH
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

            if len(stripped) > max_length:
                violations.append(
                    self.violation(
                        f"Description exceeds {max_length} characters ({len(stripped)})",
                        file_path=block.path,
                        line=desc_line,
                    )
                )

        return violations
