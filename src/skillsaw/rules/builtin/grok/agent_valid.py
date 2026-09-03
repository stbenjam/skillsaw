"""
Rule: grok-agent-valid

Validates frontmatter keys required by Grok Build for project subagents
in ``.grok/agents/*.md``. Grok requires both ``name`` and ``description``
to discover and register an agent.
"""

from typing import List

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import GrokAgentBlock

#: Required frontmatter fields for Grok Build subagents.
REQUIRED_FIELDS = ("name", "description")


class GrokAgentValidRule(Rule):
    """Validate the frontmatter of a Grok Build project subagent"""

    since = "0.20.0"

    repo_types = frozenset({RepositoryType.GROK_PROJECT})

    @property
    def rule_id(self) -> str:
        return "grok-agent-valid"

    @property
    def description(self) -> str:
        return ".grok/agents/*.md must declare a name and a description in frontmatter"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []

        for block in context.lint_tree.find(GrokAgentBlock):
            name = block.path.name
            if block.frontmatter_error:
                violations.append(
                    self.violation(
                        f"Agent {name} has invalid frontmatter: {block.frontmatter_error}",
                        block=block,
                        line=block.frontmatter_error_line,
                    )
                )
                continue
            if not block.has_frontmatter:
                violations.append(
                    self.violation(
                        f"Agent {name} has no frontmatter; add 'name' and 'description'",
                        block=block,
                    )
                )
                continue
            for key in REQUIRED_FIELDS:
                if block.field(key) is None:
                    violations.append(
                        self.violation(
                            f"Agent {name} is missing '{key}'",
                            block=block,
                        )
                    )

        return violations
