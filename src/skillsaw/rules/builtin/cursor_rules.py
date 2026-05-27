"""
Rules for validating .cursor/rules/*.mdc files
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.content_analysis import CursorRuleBlock
from skillsaw.rules.builtin.utils import validate_glob_patterns

_VALID_FRONTMATTER_KEYS = {"description", "globs", "alwaysApply"}


class CursorRuleFrontmatterRule(Rule):
    """Validate .cursor/rules/*.mdc frontmatter fields"""

    repo_types = {RepositoryType.DOT_CURSOR}

    @property
    def rule_id(self) -> str:
        return "cursor-rule-frontmatter"

    @property
    def description(self) -> str:
        return ".cursor/rules/*.mdc files should have valid frontmatter"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(CursorRuleBlock):
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        file_path=block.path,
                        line=block.frontmatter_error_line,
                    )
                )
                continue

            if block.frontmatter is None:
                continue

            fm = block.frontmatter

            unknown_keys = set(fm.keys()) - _VALID_FRONTMATTER_KEYS
            for key in sorted(unknown_keys):
                violations.append(
                    self.violation(
                        f"Unknown frontmatter key '{key}'. "
                        f"Valid keys: description, globs, alwaysApply",
                        file_path=block.path,
                        line=block.key_line(key),
                        severity=Severity.WARNING,
                    )
                )

            if "description" in fm:
                desc = fm["description"]
                if not isinstance(desc, str) or not desc.strip():
                    violations.append(
                        self.violation(
                            "'description' must be a non-empty string",
                            file_path=block.path,
                            line=block.key_line("description"),
                        )
                    )

            if "globs" in fm:
                globs_line = block.key_line("globs")
                for error in validate_glob_patterns(fm["globs"]):
                    violations.append(self.violation(error, file_path=block.path, line=globs_line))

            if "alwaysApply" in fm:
                if not isinstance(fm["alwaysApply"], bool):
                    violations.append(
                        self.violation(
                            "'alwaysApply' must be a boolean (true or false)",
                            file_path=block.path,
                            line=block.key_line("alwaysApply"),
                        )
                    )

        return violations
