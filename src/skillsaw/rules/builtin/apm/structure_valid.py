"""
Rule: apm-structure-valid
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import ApmNode


class ApmStructureValidRule(Rule):
    """Validate .apm/ directory structure"""

    repo_types = None  # runs when enabled; auto-enable via config + has_apm check

    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "apm-structure-valid"

    @property
    def description(self) -> str:
        return ".apm/ directory must contain skills/ or instructions/ with valid structure"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        if not context.has_apm:
            return []

        apm_nodes = context.lint_tree.find(ApmNode)
        if not apm_nodes:
            return []

        violations = []
        apm_dir = apm_nodes[0].path

        has_skills = (apm_dir / "skills").is_dir()
        has_instructions = (apm_dir / "instructions").is_dir()

        if not has_skills and not has_instructions:
            violations.append(
                self.violation(
                    ".apm/ directory should contain a 'skills/' or 'instructions/' subdirectory",
                    file_path=apm_dir,
                )
            )

        if has_skills:
            skills_dir = apm_dir / "skills"
            try:
                for item in skills_dir.iterdir():
                    if not item.is_dir() or item.name.startswith("."):
                        continue
                    if not (item / "SKILL.md").exists():
                        violations.append(
                            self.violation(
                                f"Skill directory '{item.name}' is missing SKILL.md",
                                file_path=item,
                            )
                        )
            except OSError:
                pass

        return violations
