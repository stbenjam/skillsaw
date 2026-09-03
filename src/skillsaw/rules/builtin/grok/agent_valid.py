"""
Rule: grok-agent-valid

The two frontmatter keys Grok Build needs before it will register a
``.grok/agents/*.md`` subagent. Without both, the file is on disk, in the
repository, and not in the agent list — and Grok says nothing about it.

Commands are deliberately not checked here. Grok loads a
``.grok/commands/*.md`` with no frontmatter at all, naming it from the
filename, so the same demand there would be a false positive on a file that
works.

Only :class:`GrokAgentBlock` is iterated, a node type that exists only where
Grok's project layer does, so the rule declares no ``provenance_scope``:
``.grok/`` is a tool directory no other ecosystem claims.
"""

from typing import List

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Rule, RuleViolation, Severity
from skillsaw.rules.builtin.content_analysis import GrokAgentBlock

#: The keys Grok's subagent loader requires, in the order they are reported.
#: An *empty* value satisfies each: verified against Grok Build 1.0.13, where
#: an agent carrying ``description: ""`` still registered. So the check is
#: presence of the key, not the usefulness of what is under it —
#: ``content-description-routing`` owns the quality of a description that is
#: there, and reporting an empty one twice would be one defect with two
#: names.
REQUIRED_FIELDS = ("name", "description")


class GrokAgentValidRule(Rule):
    """Validate the frontmatter of a Grok Build project subagent"""

    since = "0.20.0"

    # ``enabled: auto`` on the base default, gated on the one place these
    # files live: a checkout carrying a ``.grok/`` project layer.
    repo_types = frozenset({RepositoryType.GROK_PROJECT})

    @property
    def rule_id(self) -> str:
        return "grok-agent-valid"

    @property
    def description(self) -> str:
        return ".grok/agents/*.md must declare a name and a description in frontmatter"

    def default_severity(self) -> Severity:
        # The file does not load. Grok drops the subagent and reports
        # nothing, so from the outside it is indistinguishable from an agent
        # the model simply never chose.
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
