"""AgentSkill name format validation rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, AutofixResult, AutofixConfidence, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.content_analysis import SkillBlock

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

    def fix(
        self, context: RepositoryContext, violations: List[RuleViolation]
    ) -> List[AutofixResult]:
        results: List[AutofixResult] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            original = v.file_path.read_text(encoding="utf-8")
            match = re.search(r"^name:\s*(.+)$", original, re.MULTILINE)
            if not match:
                continue
            old_name = match.group(1).strip()
            if "does not match directory" in v.message:
                new_name = v.file_path.parent.name
            else:
                new_name = _to_kebab(old_name)
            if new_name == old_name or not NAME_PATTERN.match(new_name):
                continue
            fixed = original[: match.start()] + f"name: {new_name}" + original[match.end() :]

            def _record_rename(root=context.root_path, old=old_name, new=new_name):
                _add_rename(root, old, new)

            results.append(
                AutofixResult(
                    rule_id=self.rule_id,
                    file_path=v.file_path,
                    confidence=AutofixConfidence.SAFE,
                    original_content=original,
                    fixed_content=fixed,
                    description=f"Renamed '{old_name}' to '{new_name}'",
                    violations_fixed=[v],
                    # Recording the rename is a repository state change; defer
                    # it to apply time so dry-run stays side-effect free.
                    on_apply=_record_rename,
                )
            )
        return results
