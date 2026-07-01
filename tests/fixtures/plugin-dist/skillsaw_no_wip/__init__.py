"""Example skillsaw plugin used by the integration tests.

Laid out exactly like a real published plugin: the distribution metadata in
the sibling ``.dist-info`` directory registers this module under the
``skillsaw.plugins`` entry point group, so adding the fixture directory to
``PYTHONPATH`` makes it discoverable just like a pip-installed package.
"""

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


class NoWipMarkersRule(Rule):
    """Instruction files should not ship work-in-progress markers."""

    autofix_confidence = AutofixConfidence.SAFE
    config_schema = {
        "markers": {
            "type": "list",
            "default": ["WIP:"],
            "description": "Markers that flag unfinished instructions",
        },
    }

    @property
    def rule_id(self) -> str:
        return "no-wip-markers"

    @property
    def description(self) -> str:
        return "Instruction files should not contain work-in-progress markers"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def _markers(self) -> List[str]:
        return self.config.get("markers", self.config_schema["markers"]["default"])

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        markers = self._markers()
        for block in context.lint_tree.find(InstructionBlock):
            content = block.read_body(strip_code_blocks=False)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if any(marker in line for marker in markers):
                    violations.append(
                        self.violation(
                            f"Work-in-progress marker: {line.strip()}",
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
                        description="Removed work-in-progress marker lines",
                        violations_fixed=file_violations,
                    )
                )
        return results


SKILLSAW_RULES = [NoWipMarkersRule]
