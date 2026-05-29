"""Command file naming rule"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity, AutofixConfidence, FixOp
from skillsaw.context import RepositoryContext


class CommandNamingRule(Rule):
    """Check that command files use kebab-case naming"""

    autofix_confidence = AutofixConfidence.SUGGEST

    @property
    def rule_id(self) -> str:
        return "command-naming"

    @property
    def description(self) -> str:
        return "Command files should use kebab-case naming"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        from skillsaw.rules.builtin.content_analysis import CommandBlock

        violations = []

        for cmd_block in context.lint_tree.find(CommandBlock):
            cmd_file = cmd_block.path
            cmd_name = cmd_file.stem
            if not self._is_kebab_case(cmd_name):
                violations.append(
                    self.violation(
                        f"Command name '{cmd_name}' should use kebab-case", file_path=cmd_file
                    )
                )

        return violations

    @staticmethod
    def _is_kebab_case(name: str) -> bool:
        return bool(re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name))

    @staticmethod
    def _to_kebab(name: str) -> str:
        s = re.sub(r"([a-z])([A-Z])", r"\1-\2", name)
        s = re.sub(r"[^a-z0-9]+", "-", s.lower())
        s = re.sub(r"-+", "-", s).strip("-")
        return s

    def fix(self, context: RepositoryContext, violations: List[RuleViolation]) -> List[FixOp]:
        results: List[FixOp] = []
        for v in violations:
            if not v.file_path or not v.file_path.exists():
                continue
            old_path = v.file_path
            old_name = old_path.stem
            new_name = self._to_kebab(old_name)
            if not self._is_kebab_case(new_name) or new_name == old_name:
                continue
            new_path = old_path.with_name(f"{new_name}.md")
            if new_path.exists() and new_path.resolve() != old_path.resolve():
                continue
            results.append(
                self.rename_fix(
                    file_path=new_path,
                    rename_from=old_path,
                    description=f"Rename '{old_name}.md' to '{new_name}.md'",
                    violations=[v],
                    confidence=AutofixConfidence.SUGGEST,
                )
            )
        return results
