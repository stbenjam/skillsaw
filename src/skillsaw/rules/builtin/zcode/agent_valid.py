"""
Rule: zcode-agent-valid

Checks the frontmatter ZCode requires of a project subagent in
``.zcode/agents/*.md``: frontmatter must be present, and so must a non-empty
``name`` and ``description``, or ZCode skips the agent
(``packages/shared/src/subagent-profile-parser.ts:33-58`` in
``zai-org/ZCode``).
"""

from typing import List

from skillsaw.blocks import ZCodeAgentBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Rule, RuleViolation, Severity

from ._helpers import ZCODE_PROJECT_REPO_TYPES

REQUIRED_FIELDS = ("name", "description")

#: ``memory`` values ZCode accepts; any other value is reported and ignored
#: (``subagent-profile-parser.ts:31``).
MEMORY_SCOPES = ("user", "project", "local")


class ZCodeAgentValidRule(Rule):
    """Validate the frontmatter of a ZCode project subagent"""

    since = "0.22.0"

    repo_types = ZCODE_PROJECT_REPO_TYPES

    @property
    def rule_id(self) -> str:
        return "zcode-agent-valid"

    @property
    def description(self) -> str:
        return ".zcode/agents/*.md must declare a name and a description in frontmatter"

    def default_severity(self) -> Severity:
        return Severity.ERROR

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations: List[RuleViolation] = []
        for block in context.lint_tree.find(ZCodeAgentBlock):
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
                        f"Agent {name} has no frontmatter, so ZCode skips it; add 'name' "
                        "and 'description'",
                        block=block,
                    )
                )
                continue
            for key in REQUIRED_FIELDS:
                field = block.field(key)
                value = field.value if field is not None else None
                if value is None or isinstance(value, (dict, list, set)) or not str(value).strip():
                    violations.append(
                        self.violation(
                            f"Agent {name} needs a non-empty '{key}'; ZCode skips the agent "
                            "without one",
                            block=block,
                            line=field.field_line if field is not None else None,
                        )
                    )
            memory = block.field("memory")
            if memory is not None and memory.value not in MEMORY_SCOPES:
                violations.append(
                    self.violation(
                        f"Agent {name} 'memory' must be one of {', '.join(MEMORY_SCOPES)}; "
                        "ZCode ignores the value",
                        block=block,
                        line=memory.field_line,
                        severity=Severity.WARNING,
                    )
                )
        return violations
