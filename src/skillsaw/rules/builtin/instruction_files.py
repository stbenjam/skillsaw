"""
Rules for validating AI coding assistant instruction files
(AGENTS.md, CLAUDE.md, GEMINI.md)
"""

import re
from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.rules.builtin.content_analysis import (
    AgentsMdBlock,
    ClaudeMdBlock,
    GeminiMdBlock,
    InstructionBlock,
    _strip_fenced_code_blocks,
)
from skillsaw.rules.builtin.utils import read_text

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

_IMPORT_RE = re.compile(r"^\s*@(\S+)")


class InstructionFileValidRule(Rule):
    """Check that instruction files are valid UTF-8 and non-empty"""

    formats = ALL_INSTRUCTION_FORMATS

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

        for block in context.lint_tree.find(InstructionBlock):
            if block.path.name not in INSTRUCTION_FILES:
                continue

            content = read_text(block.path)
            if content is None:
                violations.append(
                    self.violation(
                        f"Failed to read {block.path.name} (invalid encoding or I/O error)",
                        file_path=block.path,
                    )
                )
                continue

            if not content.strip():
                violations.append(
                    self.violation(f"{block.path.name} is empty", file_path=block.path)
                )

        return violations


class InstructionImportsValidRule(Rule):
    """Check that @import references in instruction files resolve to existing paths"""

    formats = ALL_INSTRUCTION_FORMATS

    @property
    def rule_id(self) -> str:
        return "instruction-imports-valid"

    @property
    def description(self) -> str:
        return "Import references (@path) in AGENTS.md, CLAUDE.md, and GEMINI.md must point to existing files"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []

        import_blocks = (
            context.lint_tree.find(AgentsMdBlock)
            + context.lint_tree.find(ClaudeMdBlock)
            + context.lint_tree.find(GeminiMdBlock)
        )
        for block in import_blocks:
            file_path = block.path
            content = read_text(file_path)
            if content is None:
                continue

            content = _strip_fenced_code_blocks(content)

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
