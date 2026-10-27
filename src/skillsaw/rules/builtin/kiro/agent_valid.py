"""Structural checks shared by legacy JSON and current Kiro agents."""

from skillsaw.blocks.kiro import KiroAgentConfigRole, KiroMarkdownAgentBlock
from skillsaw.context import RepositoryType
from skillsaw.formats.kiro import agent_field_problems
from skillsaw.rule import Rule, Severity
from skillsaw.utils import read_frontmatter_commented


class KiroAgentValidRule(Rule):
    """Validate common shapes without mixing permission or hook contracts."""

    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.KIRO})

    @property
    def rule_id(self):
        return "kiro-agent-valid"

    @property
    def description(self):
        return "Kiro JSON and Markdown agents must use valid syntax and documented field types"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context):
        violations = []
        for block in context.lint_tree.find(KiroAgentConfigRole):
            line = None
            if isinstance(block, KiroMarkdownAgentBlock):
                data, error, line = read_frontmatter_commented(block.path)
                error = error or block.frontmatter_error
                line = line or block.frontmatter_error_line
                # Markdown without metadata still has an instruction body.
                if data is None and not error and not block.has_frontmatter:
                    continue
            else:
                data, error = block.raw_data, block.parse_error
            if error:
                violations.append(
                    self.violation(
                        "Invalid Kiro agent configuration syntax", file_path=block.path, line=line
                    )
                )
                continue
            if not isinstance(data, dict):
                violations.append(
                    self.violation(
                        "Kiro agent configuration must be an object", file_path=block.path
                    )
                )
                continue
            for key, problem in agent_field_problems(data):
                violations.append(
                    self.violation(problem, file_path=block.path, line=block.key_line(key))
                )
        return violations
