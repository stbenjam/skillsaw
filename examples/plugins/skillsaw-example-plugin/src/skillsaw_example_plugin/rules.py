"""The same TODO/FIXME rule from the skillsaw custom-rules docs, packaged
as a plugin so it can be shared across repositories via pip."""

import re
from typing import List

from skillsaw import (
    AutofixConfidence,
    AutofixResult,
    RepositoryContext,
    Rule,
    RuleViolation,
    Severity,
)
from skillsaw.blocks import InstructionBlock


class NoTodoInstructionsRule(Rule):
    """Instruction files should not contain TODO/FIXME comments."""

    autofix_confidence = AutofixConfidence.SAFE
    config_schema = {
        "patterns": {
            "type": "list",
            "default": ["TODO", "FIXME"],
            "description": "Patterns to flag in instruction files",
        },
    }

    @property
    def rule_id(self) -> str:
        return "no-todo-instructions"

    @property
    def description(self) -> str:
        return "Instruction files should not contain TODO/FIXME comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _pattern(self) -> "re.Pattern":
        patterns = self.config.get("patterns", self.config_schema["patterns"]["default"])
        return re.compile("|".join(rf"\b{re.escape(p)}\b" for p in patterns))

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        pattern = self._pattern()
        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    violations.append(
                        self.violation(
                            f"Found TODO/FIXME: {line.strip()}",
                            block=block,
                            line=i,
                        )
                    )
        return violations

    def fix(self, context, violations, *, provider=None) -> List[AutofixResult]:
        by_file = {}
        for v in violations:
            by_file.setdefault(v.file_path, []).append(v)

        results = []
        for path, file_violations in by_file.items():
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)
            # file_line translates block-relative lines to file lines, so the
            # fix stays scoped to the exact lines the check flagged.
            remove = {v.file_line for v in file_violations if v.file_line}
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
