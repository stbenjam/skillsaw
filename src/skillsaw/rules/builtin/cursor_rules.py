"""
Rules for validating .cursor/rules/*.mdc files
"""

from typing import List

from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.content_analysis import CursorRuleBlock
from skillsaw.rules.builtin.utils import validate_glob_patterns

_DEFAULT_VALID_KEYS = ["description", "globs", "alwaysApply"]


class CursorRuleValidRule(Rule):
    """Validate .cursor/rules/*.mdc frontmatter fields"""

    repo_types = {RepositoryType.DOT_CURSOR}

    config_schema = {
        "valid-keys": {
            "type": "list",
            "default": _DEFAULT_VALID_KEYS,
            "description": "Recognized frontmatter keys (unknown keys trigger a warning)",
        },
    }

    @property
    def rule_id(self) -> str:
        return "cursor-rule-valid"

    @property
    def description(self) -> str:
        return ".cursor/rules/*.mdc files should have valid frontmatter"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        valid_keys = set(self.config.get("valid-keys", _DEFAULT_VALID_KEYS))

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

            unknown_keys = set(fm.keys()) - valid_keys
            for key in sorted(unknown_keys):
                violations.append(
                    self.violation(
                        f"Unknown frontmatter key '{key}'",
                        file_path=block.path,
                        line=block.key_line(key),
                    )
                )

            if "description" not in fm:
                violations.append(
                    self.violation(
                        "Missing required frontmatter key 'description'",
                        file_path=block.path,
                        line=1,
                    )
                )
            else:
                desc = fm["description"]
                if not isinstance(desc, str) or not desc.strip():
                    violations.append(
                        self.violation(
                            "'description' must be a non-empty string",
                            file_path=block.path,
                            line=block.key_line("description"),
                        )
                    )

            if "globs" not in fm and "alwaysApply" not in fm:
                violations.append(
                    self.violation(
                        "Either 'globs' or 'alwaysApply' must be specified",
                        file_path=block.path,
                        line=1,
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
