"""AgentSkill evals required rule"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import SkillNode

from ._helpers import SKILL_REPO_TYPES, contained_eval_file


class AgentSkillEvalsRequiredRule(Rule):
    """Require evals/evals.json in each skill"""

    default_enabled = False

    repo_types = SKILL_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "agentskill-evals-required"

    @property
    def description(self) -> str:
        return "Require evals/evals.json for each skill (opt-in)"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for skill_node in context.lint_tree.find(SkillNode):
            skill_path = skill_node.path
            # The shared containment helper, not a bare exists(): an
            # evals.json symlinked outside the owning Codex plugin is a
            # document the plugin does not bundle, and agentskill-evals
            # refuses to validate it — satisfying the requirement with it
            # would pass a skill that ships no usable eval file.
            if contained_eval_file(context, skill_path) is None:
                violations.append(
                    self.violation(
                        "Missing evals/evals.json",
                        file_path=skill_path,
                    )
                )

        return violations
