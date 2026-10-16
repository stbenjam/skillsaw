"""Validate the stable common Rulesync authoring fields, not every compiler target."""

from skillsaw.blocks.generators import RulesyncConfigBlock, RulesyncRuleBlock
from skillsaw.context import RepositoryType
from skillsaw.formats.generators import RULESYNC_CONFIG, RULESYNC_RULE, schema_problems
from skillsaw.rule import Rule, Severity


class RulesyncSourceValidRule(Rule):
    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.RULESYNC})

    @property
    def rule_id(self):
        return "rulesync-source-valid"

    @property
    def description(self):
        return "Validate common Rulesync 32.0.0 rule frontmatter and project configuration fields"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context):
        violations = []
        for block in context.lint_tree.find(RulesyncRuleBlock):
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        block.frontmatter_error,
                        file_path=block.path,
                        line=block.frontmatter_error_line,
                    )
                )
            elif not block.has_frontmatter:
                violations.append(
                    self.violation(
                        "Rulesync rules require YAML frontmatter delimited by '---'",
                        file_path=block.path,
                    )
                )
            else:
                for path, message in schema_problems(block.raw_data, RULESYNC_RULE):
                    violations.append(
                        self.violation(
                            "Invalid Rulesync frontmatter: " + message,
                            file_path=block.path,
                            line=block.key_line(path[0]) if path else None,
                        )
                    )
        for block in context.lint_tree.find(RulesyncConfigBlock):
            if block.parse_error or block.raw_data is None:
                violations.append(
                    self.violation(
                        "Rulesync configuration must be a JSONC object",
                        file_path=block.path,
                    )
                )
                continue
            data = block.raw_data
            problems = schema_problems(data, RULESYNC_CONFIG)
            if "inputRoot" in data and "inputRoots" in data:
                problems.append(((), "choose either inputRoot or inputRoots"))
            if "targets" in data and "features" in data and isinstance(data["targets"], dict):
                problems.append(((), "object-form targets cannot be combined with features"))
            if problems:
                violations.append(
                    self.violation(
                        "Invalid Rulesync configuration: " + "; ".join(p[1] for p in problems[:4]),
                        file_path=block.path,
                    )
                )
        return violations
