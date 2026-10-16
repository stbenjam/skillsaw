"""Ruler's released project configuration contract."""

from skillsaw.blocks.generators import RulerConfigBlock
from skillsaw.context import RepositoryType
from skillsaw.formats.generators import RULER_CONFIG, schema_problems
from skillsaw.rule import Rule, Severity


class RulerConfigValidRule(Rule):
    since = "0.21.1"
    default_enabled = False
    repo_types = frozenset({RepositoryType.RULER})

    @property
    def rule_id(self):
        return "ruler-config-valid"

    @property
    def description(self):
        return "Validate .ruler/ruler.toml against the Ruler 0.3.44 configuration shape"

    def default_severity(self):
        return Severity.ERROR

    def check(self, context):
        violations = []
        for block in context.lint_tree.find(RulerConfigBlock):
            if block.parse_error:
                message = "Cannot parse Ruler TOML configuration"
            else:
                problems = schema_problems(block.raw_data, RULER_CONFIG)
                if not problems:
                    continue
                message = "Invalid Ruler configuration: " + "; ".join(p[1] for p in problems[:4])
            violations.append(self.violation(message, file_path=block.path))
        return violations
