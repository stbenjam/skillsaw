"""AgentSkill directory structure validation rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode

from ._helpers import DEFAULT_ALLOWED_DIRS


class AgentSkillStructureRule(Rule):
    """Validate skill directory structure (stricter than spec)"""

    default_enabled = False

    repo_types = {
        RepositoryType.AGENTSKILLS,
        RepositoryType.SINGLE_PLUGIN,
        RepositoryType.MARKETPLACE,
        RepositoryType.DOT_CLAUDE,
    }
    config_schema = {
        "allowed_dirs": {
            "type": "list",
            "default": sorted(DEFAULT_ALLOWED_DIRS),
            "description": "Directory names allowed in the skill root",
        },
    }

    @property
    def rule_id(self) -> str:
        return "agentskill-structure"

    @property
    def description(self) -> str:
        return (
            "Skill directories should only contain recognized subdirectories (stricter than spec)"
        )

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        allowed = set(self.config.get("allowed_dirs", DEFAULT_ALLOWED_DIRS))

        for skill_node in context.lint_tree.find(SkillNode):
            skill_path = skill_node.path
            try:
                for item in skill_path.iterdir():
                    if not item.is_dir() or item.name.startswith("."):
                        continue
                    if item.name not in allowed:
                        violations.append(
                            self.violation(
                                f"Unrecognized directory '{item.name}' "
                                f"(expected: {', '.join(sorted(allowed))})",
                                file_path=item,
                            )
                        )
            except OSError:
                pass

        return violations
