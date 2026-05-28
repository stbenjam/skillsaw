import re
from typing import List

from skillsaw import Rule, RuleViolation, Severity, RepositoryContext
from skillsaw import AutofixResult, AutofixConfidence
from skillsaw.rules.builtin.content_analysis import InstructionBlock


class NoTodoInInstructionsRule(Rule):
    """Instruction files should not contain TODO/FIXME comments."""

    autofix_confidence = AutofixConfidence.SAFE

    @property
    def rule_id(self) -> str:
        return "no-todo-instructions"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO/FIXME comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        pattern = re.compile(r"\bTODO\b|\bFIXME\b")

        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(
                        self.violation(
                            f"Found TODO/FIXME: {line.strip()}",
                            file_path=block.path,
                            line=i,
                        )
                    )
        return violations

    def fix(
        self,
        context: RepositoryContext,
        violations: List[RuleViolation],
    ) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            remove = {v.line for v in file_violations if v.line}
            fixed = "".join(ln for i, ln in enumerate(lines, start=1) if i not in remove)
            if fixed != original:
                results.append(
                    AutofixResult(
                        rule_id=self.rule_id,
                        file_path=path,
                        confidence=AutofixConfidence.SAFE,
                        original_content=original,
                        fixed_content=fixed,
                        description="Removed TODO/FIXME lines",
                        violations_fixed=file_violations,
                    )
                )
        return results
