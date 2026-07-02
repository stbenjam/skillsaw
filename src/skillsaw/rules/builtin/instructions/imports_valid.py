"""
Rule: instruction-imports-valid
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, ALL_INSTRUCTION_FORMATS
from skillsaw.rules.builtin.content_analysis import (
    AgentsMdBlock,
    ClaudeMdBlock,
    GeminiMdBlock,
)

from ._helpers import _IMPORT_RE


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
            if block.read_body(strip_code_blocks=False) is None:
                continue

            for line_num, line in block.markdown.prose_lines():
                match = _IMPORT_RE.match(line)
                if not match:
                    continue

                import_path_str = match.group(1)

                # Home-directory imports (Claude Code's ``@~/.claude/...``
                # memory syntax) reference machine-local files that are not
                # part of the repository. They're environment-specific, so
                # existence checking is always noise in CI — skip them.
                if import_path_str.startswith("~"):
                    continue

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
