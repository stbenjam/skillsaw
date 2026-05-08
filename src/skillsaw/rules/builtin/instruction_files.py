"""
Rules for validating AI coding assistant instruction files
(AGENTS.md, CLAUDE.md, GEMINI.md)
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.utils import read_text

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

IMPORT_SUPPORTING_FILES = ("CLAUDE.md", "GEMINI.md")

_IMPORT_RE = re.compile(r"^\s*@(\S+)")


class InstructionFileValidRule(Rule):
    """Check that instruction files are valid UTF-8 and non-empty"""

    @property
    def rule_id(self) -> str:
        return "instruction-file-valid"

    @property
    def description(self) -> str:
        return "Instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) must be valid and non-empty"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for filename in INSTRUCTION_FILES:
            file_path = context.root_path / filename
            if not file_path.exists():
                continue

            content = read_text(file_path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read {filename} (invalid encoding or I/O error)",
                        file_path=file_path,
                    )
                )
                continue

            if not content.strip():
                violations.append(self.violation(f"{filename} is empty", file_path=file_path))

        return violations


class InstructionImportsValidRule(Rule):
    """Check that @import references in instruction files resolve to existing paths"""

    @property
    def rule_id(self) -> str:
        return "instruction-imports-valid"

    @property
    def description(self) -> str:
        return "Import references (@path) in CLAUDE.md and GEMINI.md must point to existing files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        for filename in IMPORT_SUPPORTING_FILES:
            file_path = context.root_path / filename
            if not file_path.exists():
                continue

            content = read_text(file_path)
            if content is None:
                continue

            for line_num, line in enumerate(content.splitlines(), 1):
                match = _IMPORT_RE.match(line)
                if not match:
                    continue

                import_path_str = match.group(1)
                target = (context.root_path / import_path_str).resolve()

                try:
                    target.relative_to(context.root_path.resolve())
                except ValueError:
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' escapes repository root",
                            file_path=file_path,
                            line=line_num,
                        )
                    )
                    continue

                if not target.exists():
                    violations.append(
                        self.violation(
                            f"Import '@{import_path_str}' references non-existent path",
                            file_path=file_path,
                            line=line_num,
                        )
                    )

        return violations
