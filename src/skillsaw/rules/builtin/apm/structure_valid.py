"""
Rule: apm-structure-valid
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import ApmNode

# Primitive subdirectories APM recognizes under `.apm/` (microsoft/apm
# package-anatomy). A package may provide any subset; requiring only
# skills/ or instructions/ produced false positives on packages built
# purely from prompts/, agents/, context/, or hooks/.
APM_PRIMITIVE_DIRS = ("skills", "instructions", "prompts", "agents", "context", "hooks")


class ApmStructureValidRule(Rule):
    """Validate .apm/ directory structure"""

    repo_types = None  # runs when enabled; auto-enable via config + has_apm check

    since = "0.7.0"

    @property
    def rule_id(self) -> str:
        return "apm-structure-valid"

    @property
    def description(self) -> str:
        return (
            ".apm/ directory must contain a recognized primitive subdirectory with valid structure"
        )

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
        has_primitive = any((apm_dir / name).is_dir() for name in APM_PRIMITIVE_DIRS)

        if not has_primitive:
            expected = ", ".join(f"'{name}/'" for name in APM_PRIMITIVE_DIRS)
            violations.append(
                self.violation(
                    f".apm/ directory should contain a recognized primitive subdirectory "
                    f"({expected})",
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
